"""Live-check receipts are tested with explicitly synthetic transport data.

These unit tests do not establish actual internet/provider availability. The
separate script's normal CLI calls the real fixed HTTPS provider without stubs.
"""
import base64
import hashlib
from copy import deepcopy

import pytest

from rocket_workbench.motor_catalog import CatalogUnavailable, MotorCatalog
from scripts.motor_catalog_smoke import live_check, verify_download

MOTOR_ID = "a" * 24
CURVE_ID = "b" * 24
CURVE = b"; SYNTHETIC smoke-receipt fixture, no certification\nQA-J350 54 300 0 0.2 0.5 QA\n0 0\n1 100\n2 0\n"
ROW = {"motorId": MOTOR_ID, "simfileId": CURVE_ID, "format": "RASP", "source": "user",
       "license": "PD", "data": base64.b64encode(CURVE).decode("ascii")}


def fixture_transport(endpoint, criteria):
    if endpoint == "search.json":
        return {"matches": 1, "results": [{"motorId": MOTOR_ID, "designation": "QA-J350",
                "manufacturer": "Synthetic QA", "diameter": 54, "length": 300, "dataFiles": 1}]}
    assert endpoint == "download.json"
    assert criteria["motorIds"] == [MOTOR_ID]
    return {"results": [deepcopy(ROW)]}


def test_smoke_receipt_records_real_file_checks_without_claiming_fixture_is_live():
    receipt = live_check("QA-J350", transport=fixture_transport)
    assert receipt["status"] == "ok", receipt
    assert receipt["actual_request"] is False
    assert receipt["project_modified"] is False
    assert receipt["synthetic_fallback"] is False
    assert len(receipt["requests"]) == 2
    # Independent triangular thrust area and exact downloaded-byte fingerprint.
    assert receipt["curve"]["total_impulse_ns"] == 100
    assert receipt["curve"]["curve_sha256"] == hashlib.sha256(CURVE).hexdigest()
    assert receipt["curve"]["provenance"]["motor_id"] == MOTOR_ID
    assert receipt["curve"]["provenance"]["simfile_id"] == CURVE_ID
    assert "data" not in receipt["curve"]
    assert "review_token" not in receipt
    assert receipt["provider_certification_independently_verified"] is False


def test_smoke_receipt_preserves_unavailability_instead_of_synthetic_success():
    def blocked(*_):
        raise CatalogUnavailable("Provider is unavailable (HTTP 403); use local ENG/RSE.")
    receipt = live_check("QA-J350", transport=blocked)
    assert receipt["status"] == "failed"
    assert receipt["actual_request"] is False
    assert receipt["project_modified"] is False
    assert receipt["error_type"] == "CatalogUnavailable"
    assert "HTTP 403" in receipt["error"]
    assert "curve" not in receipt
    assert len(receipt["requests"]) == 1


@pytest.mark.parametrize("damage", ["hash", "source", "summary", "nonfinite"])
def test_integrity_checks_reject_changed_file_attribution_and_physical_data(damage):
    catalog = MotorCatalog(fixture_transport)
    preview = catalog.preview(MOTOR_ID, CURVE_ID)
    motor = catalog.reviewed_motor(preview["review_token"])
    if damage == "hash":
        preview["provenance"]["curve_sha256"] = "0" * 64
    elif damage == "source":
        preview["provenance"]["source_url"] = "https://unrelated.invalid/curve"
    elif damage == "summary":
        preview["summary"]["total_impulse_ns"] = 101
    else:
        motor.curve[1][1] = float("nan")
    with pytest.raises(ValueError):
        verify_download(preview, motor, ROW, MOTOR_ID, CURVE_ID)
