"""Official JSON protocol, synthetic file reference values, and safe local import.

These tests intentionally stub the provider transport. They verify integration,
not the availability of the external service or a real motor's certification.
"""
import base64
import hashlib
import json
import socket
import time
import urllib.error
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from rocket_workbench.api import create_app
from rocket_workbench.motor_catalog import (
    API_URL, MAX_CACHE_ENTRIES, MAX_RESPONSE_BYTES, CatalogUnavailable, MotorCatalog,
    _NoRedirect, _strict_json, provider_request,
)

MOTOR_ID = "56a409280002310000000146"
CURVE_ID = "56a409280002e90000000071"
OTHER_ID = "56a409280002e90000000072"
ENG = b"; Synthetic protocol test, not measured thrust\nQA-J350 54 410 0 0.2 0.5 QA\n0 0\n1 100\n2 0\n"
RSE = b'<engine-database><engine-list><engine code="QA-J350" dia="54" len="410" initWt="500" propWt="200" mfg="QA"><data><eng-data t="0" f="0"/><eng-data t="1" f="100"/><eng-data t="2" f="0"/></data></engine></engine-list></engine-database>'


def provider_fixture(endpoint, criteria):
    if endpoint == "search.json":
        return {"matches": 1, "criteria": [], "results": [{"motorId": MOTOR_ID,
            "manufacturer": "QA synthetic", "designation": "QA-J350", "diameter": 54,
            "length": 410, "totImpulseNs": 100, "avgThrustN": 50, "maxThrustN": 100,
            "burnTimeS": 2, "dataFiles": 2, "certOrg": "Synthetic fixture, no certification"}]}
    assert endpoint == "download.json"
    assert criteria == {"motorIds": [MOTOR_ID], "data": "file", "maxResults": 20}
    return {"results": [{"motorId": MOTOR_ID, "simfileId": CURVE_ID, "format": "RASP",
        "source": "user", "license": "PD", "data": base64.b64encode(ENG).decode()},
        {"motorId": MOTOR_ID, "simfileId": OTHER_ID, "format": "RockSim", "source": "mfr",
         "license": "free", "data": base64.b64encode(RSE).decode()}]}


def test_search_uses_official_camel_case_and_converts_mm_to_si():
    calls = []
    def transport(endpoint, criteria):
        calls.append((endpoint, criteria))
        return provider_fixture(endpoint, criteria)
    answer = MotorCatalog(transport).search(" QA-J350 ", " QA ", 12)
    assert calls == [("search.json", {"maxResults": 12, "designation": "QA-J350", "manufacturer": "QA"})]
    motor = answer["motors"][0]
    assert motor["diameter_m"] == pytest.approx(.054)
    assert motor["length_m"] == pytest.approx(.410)
    assert motor["total_impulse_ns"] == 100
    assert motor["source_url"] == "https://www.thrustcurve.org/motors/QA%20synthetic/QA-J350/"
    assert answer["fetched_at"].endswith("+00:00")
    with pytest.raises(ValueError, match="designation"):
        MotorCatalog(transport).search("", "")
    with pytest.raises(ValueError, match="limit"):
        MotorCatalog(transport).search("QA", limit=500)


@pytest.mark.parametrize("identity,format", [(CURVE_ID, "RASP"), (OTHER_ID, "RockSim")])
def test_preview_decodes_real_file_reader_and_persists_provenance(identity, format):
    catalog = MotorCatalog(provider_fixture)
    rows = catalog.curves(MOTOR_ID)["curves"]
    assert all("data" not in row for row in rows)
    preview = catalog.preview(MOTOR_ID, identity)
    motor = catalog.reviewed_motor(preview["review_token"])
    # Independent triangle area 1/2 × 2 seconds × 100 N, and g/mm units.
    assert preview["summary"]["total_impulse_ns"] == 100
    assert preview["summary"]["burn_time_s"] == 2
    assert motor.curve == [[0, 0], [1, 100], [2, 0]]
    assert motor.dry_mass == pytest.approx(.3)
    assert motor.propellant_mass == pytest.approx(.2)
    assert motor.diameter == pytest.approx(.054)
    assert motor.length == pytest.approx(.410)
    assert motor.provenance["format"] == format
    assert motor.provenance["curve_sha256"] == hashlib.sha256(ENG if format == "RASP" else RSE).hexdigest()
    assert motor.provenance["retrieval_endpoint"] == API_URL + "download.json"
    assert len(preview["warnings"]) == 2
    motor.name = "Changed client copy"
    assert catalog.reviewed_motor(preview["review_token"]).name == "QA-J350"


def test_unknown_curve_bad_encoding_and_mismatched_motor_rejected():
    catalog = MotorCatalog(provider_fixture)
    with pytest.raises(ValueError, match="available files"):
        catalog.preview(MOTOR_ID, "56a409280002e90000000073")
    for change, message in [({"data": "!not-base64!"}, "encoding"), ({"motorId": OTHER_ID}, "different motor"),
                            ({"data": base64.b64encode(b"invalid file").decode()}, "cannot be imported")]:
        def invalid(endpoint, criteria):
            answer = provider_fixture(endpoint, criteria)
            answer["results"][0].update(change)
            return answer
        with pytest.raises(CatalogUnavailable, match=message):
            MotorCatalog(invalid).preview(MOTOR_ID, CURVE_ID)


def test_cache_bounded_expiring_and_provider_errors_not_fabricated():
    calls = []
    def transport(endpoint, criteria):
        calls.append(endpoint)
        return provider_fixture(endpoint, criteria)
    catalog = MotorCatalog(transport)
    catalog.curves(MOTOR_ID)
    for _ in range(MAX_CACHE_ENTRIES + 5):
        catalog.preview(MOTOR_ID, CURVE_ID)
    assert len(catalog._reviews) == MAX_CACHE_ENTRIES
    assert calls == ["download.json"]
    preview = catalog.preview(MOTOR_ID, CURVE_ID)
    catalog._reviews[preview["review_token"]] = (time.monotonic() - 1000, catalog.reviewed_motor(preview["review_token"]))
    with pytest.raises(ValueError, match="expired"):
        catalog.reviewed_motor(preview["review_token"])
    with pytest.raises(CatalogUnavailable, match="complete this lookup"):
        MotorCatalog(lambda *_: {"error": "remote private text", "results": []}).search("QA")
    with pytest.raises(CatalogUnavailable, match="results list"):
        MotorCatalog(lambda *_: {"results": "oops"}).search("QA")


def test_reviewed_import_preserves_latest_edits_and_never_assigns_configuration(tmp_path):
    app = create_app(data_dir=tmp_path)
    app.state.motor_catalog = MotorCatalog(provider_fixture)
    with TestClient(app) as client:
        original = client.get("/api/project").json()
        assert client.post("/api/motors/search", json={"query": "QA-J350"}).status_code == 200
        assert client.get(f"/api/motors/{MOTOR_ID}/curves").status_code == 200
        response = client.post("/api/motors/preview", json={"motor_id": MOTOR_ID, "simfile_id": CURVE_ID})
        assert response.status_code == 200
        preview = response.json()
        unchanged = client.get("/api/project").json()
        assert unchanged == original
        changed = deepcopy(original)
        changed["name"] = "Edited after network preview"
        changed["components"][0]["name"] = "Keep my component edit"
        client.put("/api/project", json=changed)
        imported = client.post("/api/motors/import", json={"project_id": original["id"], "review_token": preview["review_token"]})
        assert imported.status_code == 200, imported.text
        value = imported.json()
        assert value["name"] == changed["name"]
        assert value["components"] == changed["components"]
        assert value["configurations"] == changed["configurations"]
        assert len(value["motors"]) == len(original["motors"]) + 1
        assert value["motors"][-1]["provenance"]["curve_sha256"] == hashlib.sha256(ENG).hexdigest()
        duplicate = client.post("/api/motors/import", json={"project_id": original["id"], "review_token": preview["review_token"]})
        assert len(duplicate.json()["motors"]) == len(value["motors"])
        with TestClient(create_app(data_dir=tmp_path)) as restarted:
            restored = restarted.get("/api/project").json()
            assert restored["motors"][-1]["curve"] == [[0, 0], [1, 100], [2, 0]]
            assert restored["motors"][-1]["provenance"] == value["motors"][-1]["provenance"]
            assert restored["configurations"] == changed["configurations"]
        client.post("/api/project/demo")
        stale = client.post("/api/motors/import", json={"project_id": original["id"], "review_token": preview["review_token"]})
        assert stale.status_code == 409
        assert len(client.get("/api/project").json()["motors"]) == len(original["motors"])


def test_offline_invalid_id_token_and_session_leave_project_unchanged():
    app = create_app(token="catalog-session")
    def offline(*_):
        raise CatalogUnavailable("Network unavailable; import a local .eng/.rse file.")
    app.state.motor_catalog = MotorCatalog(offline)
    with TestClient(app) as client:
        headers = {"X-Rocket-Session": "catalog-session"}
        before = client.get("/api/project", headers=headers).json()
        assert client.post("/api/motors/search", json={"query": "QA"}).status_code == 403
        failed = client.post("/api/motors/search", json={"query": "QA"}, headers=headers)
        assert failed.status_code == 503 and "local .eng/.rse" in failed.json()["detail"]
        assert client.get("/api/motors/https://foreign.invalid/curves", headers=headers).status_code == 404
        assert client.post("/api/motors/preview", json={"motor_id": "not-a-provider-id", "simfile_id": CURVE_ID}, headers=headers).status_code == 422
        assert client.post("/api/motors/import", json={"project_id": before["id"], "review_token": "client-forged"}, headers=headers).status_code == 400
        assert client.get("/api/project", headers=headers).json() == before


def test_transport_uses_fixed_https_post_timeout_and_response_limit(monkeypatch):
    class Response:
        headers = {}
        def __init__(self, raw): self.raw, self.cursor = raw, 0
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self, size):
            result = self.raw[self.cursor:self.cursor + size]
            self.cursor += len(result)
            return result
    calls = []
    class Opener:
        def open(self, req, timeout):
            calls.append((req.full_url, req.method, json.loads(req.data), timeout))
            return Response(b'{"results":[]}')
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: Opener())
    assert provider_request("search.json", {"designation": "QA"}) == {"results": []}
    assert calls == [(API_URL + "search.json", "POST", {"designation": "QA"}, 15)]
    with pytest.raises(ValueError, match="Unknown"):
        provider_request("https://foreign.invalid/", {})
    class OversizeOpener:
        def open(self, *_args, **_kwargs): return Response(b" " * (MAX_RESPONSE_BYTES + 1))
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: OversizeOpener())
    with pytest.raises(CatalogUnavailable, match="size limit"):
        provider_request("search.json", {})
    with pytest.raises(CatalogUnavailable, match="redirected"):
        _NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://foreign.invalid/")


def test_transport_overall_deadline_rejects_slow_stream(monkeypatch):
    class Response:
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self, _size): raise AssertionError("Expired response must not be read")
    class Opener:
        def open(self, *_args, **_kwargs): return Response()
    times = iter([0, 16])
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: Opener())
    monkeypatch.setattr("rocket_workbench.motor_catalog.time.monotonic", lambda: next(times))
    with pytest.raises(CatalogUnavailable, match="timed out"):
        provider_request("search.json", {})


@pytest.mark.parametrize("raw", [b'{"results":NaN}', b'{"results":1e999}', b'[]', b'not JSON'])
def test_strict_provider_json_rejects_nonfinite_or_invalid_responses(raw):
    with pytest.raises(CatalogUnavailable):
        _strict_json(raw)


@pytest.mark.parametrize("failure", [urllib.error.URLError("offline"), socket.timeout("timeout"), urllib.error.HTTPError(API_URL, 503, "offline", {}, None)])
def test_transport_network_errors_are_friendly_and_do_not_echo_remote_data(monkeypatch, failure):
    class Opener:
        def open(self, *_args, **_kwargs): raise failure
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: Opener())
    with pytest.raises(CatalogUnavailable, match=r"local \.eng/\.rse"):
        provider_request("search.json", {})
