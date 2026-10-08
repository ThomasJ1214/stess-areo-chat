"""Bounded, explicit ThrustCurve.org discovery; downloaded curves remain user-reviewed.

Protocol reference: JohnCoker/thrustcurve3 api/src/{api,types}.ts and
routes/api_v1.js at 577afa62302f70c6b2ba04e97a39240638cd704b. The official
JSON API returns dimensions in mm and base64-encoded ENG/RSE files. No web
scraping, credentials, arbitrary URLs, generated curves, or external programs.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Callable

from .imports import import_motor
from .models import Motor

PROVIDER = "ThrustCurve.org"
BASE_URL = "https://www.thrustcurve.org"
API_URL = BASE_URL + "/api/v1/"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_CURVE_BYTES = 256 * 1024
MAX_CURVES = 20
MAX_RESULTS = 50
TIMEOUT = 15
CACHE_SECONDS = 15 * 60
MAX_CACHE_ENTRIES = 60
MAX_CACHED_MOTORS = 8
MAX_CURVE_SAMPLES = 20000
ID_PATTERN = re.compile(r"^[a-fA-F0-9]{24}$")


class CatalogUnavailable(Exception):
    """Remote service/network failure, distinct from a bad local request."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Only the fixed HTTPS provider endpoints are permitted.
        raise CatalogUnavailable("ThrustCurve.org redirected this request. Try again later or import a local .eng/.rse file.")


def _strict_json(raw: bytes) -> dict:
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Non-finite JSON number")
        return number
    try:
        value = json.loads(raw, parse_float=finite_float,
                           parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise CatalogUnavailable("ThrustCurve.org returned invalid JSON. Try again later or import a local motor file.") from exc
    if not isinstance(value, dict):
        raise CatalogUnavailable("ThrustCurve.org returned an unexpected response.")
    return value


def provider_request(endpoint: str, criteria: dict) -> dict:
    if endpoint not in {"search.json", "download.json"}:
        raise ValueError("Unknown motor catalog operation.")
    request = urllib.request.Request(API_URL + endpoint,
        data=json.dumps(criteria, allow_nan=False).encode("utf8"), method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "Accept-Encoding": "identity", "User-Agent": "RocketWorkbench/ThrustCurveClient"})
    deadline = time.monotonic() + TIMEOUT
    try:
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(request, timeout=TIMEOUT) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_RESPONSE_BYTES:
                raise CatalogUnavailable("The motor catalog response exceeds the application's size limit. Narrow the search.")
            raw = bytearray()
            # read1 returns available bytes rather than waiting for a whole
            # multi-megabyte response. Apply an overall read deadline as well
            # as the socket timeout, so slow streams cannot run indefinitely.
            read = getattr(response, "read1", response.read)
            while True:
                if time.monotonic() >= deadline:
                    raise CatalogUnavailable("ThrustCurve.org timed out. Try again later or import a local .eng/.rse file.")
                chunk = read(min(64 * 1024, MAX_RESPONSE_BYTES + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise CatalogUnavailable("The motor catalog response exceeds the application's size limit. Narrow the search.")
            return _strict_json(bytes(raw))
    except urllib.error.HTTPError as exc:
        raise CatalogUnavailable(f"ThrustCurve.org is unavailable (HTTP {exc.code}). Try again later or import a local .eng/.rse file.") from exc
    except (urllib.error.URLError, OSError, socket.timeout, TimeoutError) as exc:
        raise CatalogUnavailable("Cannot connect to ThrustCurve.org. Check your internet connection, proxy, or firewall; local .eng/.rse import still works.") from exc
    except ValueError as exc:
        raise CatalogUnavailable("ThrustCurve.org returned an invalid response header.") from exc


def _id(value) -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError("Select a valid ThrustCurve.org motor or curve identifier.")
    return value.lower()


def _text(value, limit=200) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _number(value, scale=1, positive=False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    try:
        if not math.isfinite(value):
            return None
    except OverflowError:
        return None
    if value < 0 or (positive and value <= 0):
        return None
    return float(value) * scale


def _response_rows(value: dict) -> list[dict]:
    if value.get("error") or value.get("errors"):
        raise CatalogUnavailable("ThrustCurve.org could not complete this lookup. Check the exact designation/manufacturer and retry.")
    for criterion in value.get("criteria", []) if isinstance(value.get("criteria"), list) else []:
        if isinstance(criterion, dict) and criterion.get("error"):
            raise CatalogUnavailable("ThrustCurve.org rejected a search filter. Check the exact designation/manufacturer and retry.")
    rows = value.get("results")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise CatalogUnavailable("ThrustCurve.org returned an unexpected results list.")
    return rows


class MotorCatalog:
    """Session-local bounded cache; preview/import uses the identical parsed curve."""

    def __init__(self, transport: Callable[[str, dict], dict] = provider_request):
        self.transport = transport
        self._lock = threading.RLock()
        self._curves: OrderedDict[str, tuple[float, list[dict]]] = OrderedDict()
        self._reviews: OrderedDict[str, tuple[float, Motor]] = OrderedDict()

    def _prune(self, cache, max_entries=MAX_CACHE_ENTRIES):
        cutoff = time.monotonic() - CACHE_SECONDS
        for key in list(cache):
            if cache[key][0] < cutoff:
                del cache[key]
        while len(cache) > max_entries:
            cache.popitem(last=False)

    def search(self, query: str = "", manufacturer: str = "", limit: int = 30) -> dict:
        query, manufacturer = query.strip(), manufacturer.strip()
        if len(query) > 80 or len(manufacturer) > 80 or not (query or manufacturer):
            raise ValueError("Enter a motor designation (for example J350W) or manufacturer, up to 80 characters.")
        if not 1 <= limit <= MAX_RESULTS:
            raise ValueError("Search limit must be between 1 and 50.")
        # The production API currently reports zero matches for its documented
        # hasDataFiles filter even for motors whose returned dataFiles count is
        # positive (checked against AeroTech J350W, 2026-10-08). Search without
        # that filter and preserve the actual per-motor count for the UI. This
        # also lets a user distinguish a real no-curve motor from no matches.
        criteria = {"maxResults": limit}
        if query:
            criteria["designation"] = query
        if manufacturer:
            criteria["manufacturer"] = manufacturer
        value = self.transport("search.json", criteria)
        rows, motors = _response_rows(value), []
        for row in rows[:limit]:
            try:
                identity = _id(row.get("motorId"))
            except ValueError as exc:
                raise CatalogUnavailable("ThrustCurve.org returned an invalid motor identifier.") from exc
            manufacturer_slug = urllib.parse.quote(_text(row.get("manufacturerAbbrev")) or _text(row.get("manufacturer")), safe="")
            designation_slug = urllib.parse.quote(_text(row.get("designation")) or _text(row.get("commonName")), safe="")
            motors.append({"motor_id": identity, "manufacturer": _text(row.get("manufacturer")),
                "designation": _text(row.get("designation")), "common_name": _text(row.get("commonName")),
                "diameter_m": _number(row.get("diameter"), .001, True), "length_m": _number(row.get("length"), .001, True),
                "total_impulse_ns": _number(row.get("totImpulseNs")), "average_thrust_n": _number(row.get("avgThrustN")),
                "max_thrust_n": _number(row.get("maxThrustN")), "burn_time_s": _number(row.get("burnTimeS")),
                "type": _text(row.get("type")), "cert_org": _text(row.get("certOrg")),
                "data_files": int(_number(row.get("dataFiles")) or 0), "availability": _text(row.get("availability")),
                "delays": _text(row.get("delays")), "source_url": f"{BASE_URL}/motors/{manufacturer_slug}/{designation_slug}/"})
        matches = _number(value.get("matches"))
        return {"provider": PROVIDER, "source_url": BASE_URL + "/motors/search.html",
                "fetched_at": datetime.now(timezone.utc).isoformat(), "total": int(matches) if matches is not None else len(motors),
                "motors": motors}

    def curves(self, motor_id: str) -> dict:
        motor_id = _id(motor_id)
        with self._lock:
            self._prune(self._curves, MAX_CACHED_MOTORS)
            cached = self._curves.get(motor_id)
        if cached:
            rows = cached[1]
        else:
            value = self.transport("download.json", {"motorIds": [motor_id], "data": "file", "maxResults": MAX_CURVES})
            fetched_at = datetime.now(timezone.utc).isoformat()
            rows = []
            for entry in _response_rows(value)[:MAX_CURVES]:
                try:
                    identity, entry_motor = _id(entry.get("simfileId")), _id(entry.get("motorId"))
                except ValueError as exc:
                    raise CatalogUnavailable("ThrustCurve.org returned an invalid curve identifier.") from exc
                if entry_motor != motor_id:
                    raise CatalogUnavailable("ThrustCurve.org returned a curve for a different motor. Nothing was imported.")
                if entry.get("format") not in {"RASP", "RockSim"}:
                    continue
                # Decoding is delayed until the user selects a curve; metadata
                # review remains available even when one provider file is bad.
                rows.append({"motor_id": motor_id, "simfile_id": identity, "format": entry["format"],
                    "source": _text(entry.get("source"), 30), "license": _text(entry.get("license"), 40),
                    "source_url": f"{BASE_URL}/simfiles/{identity}/", "fetched_at": fetched_at,
                    "data": entry.get("data")})
            with self._lock:
                self._curves[motor_id] = (time.monotonic(), rows)
                self._prune(self._curves, MAX_CACHED_MOTORS)
        return {"provider": PROVIDER, "motor_id": motor_id,
                "curves": [{key: value for key, value in row.items() if key != "data"} for row in rows],
                "limit": MAX_CURVES}

    def preview(self, motor_id: str, simfile_id: str) -> dict:
        motor_id, simfile_id = _id(motor_id), _id(simfile_id)
        self.curves(motor_id)
        with self._lock:
            cached = self._curves.get(motor_id)
            row = next((item.copy() for item in cached[1] if item["simfile_id"] == simfile_id), None) if cached else None
        if row is None:
            raise ValueError("This curve is not in the reviewed motor's available files. Search/select the motor again.")
        encoded = row.pop("data")
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_CURVE_BYTES + 2) // 3):
            raise CatalogUnavailable("The selected motor file is missing or exceeds the 256 KiB curve limit.")
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise CatalogUnavailable("The selected motor file has invalid encoding. Choose another curve or import a local file.") from exc
        if len(payload) > MAX_CURVE_BYTES:
            raise CatalogUnavailable("The selected motor file exceeds the 256 KiB curve limit.")
        extension = "eng" if row["format"] == "RASP" else "rse"
        try:
            motors = import_motor(payload, f"thrustcurve-{simfile_id}.{extension}")
        except ValueError as exc:
            raise CatalogUnavailable(f"The selected provider curve cannot be imported: {str(exc)[:300]} Choose another file.") from exc
        if len(motors) != 1:
            raise CatalogUnavailable("The selected provider file contains multiple motors. Download it separately and review a local import.")
        motor = motors[0]
        if len(motor.curve) > MAX_CURVE_SAMPLES:
            raise CatalogUnavailable("The selected curve exceeds the 20,000-sample online import limit. Review and import it as a local file instead.")
        provenance = row | {"provider": PROVIDER, "curve_sha256": hashlib.sha256(payload).hexdigest(),
                             "retrieval_endpoint": API_URL + "download.json"}
        motor.provenance = provenance
        motor.source = f"{PROVIDER} · {row['source'] or 'source unspecified'} · {row['source_url']}"
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._reviews[token] = (time.monotonic(), motor.model_copy(deep=True))
            self._prune(self._reviews)
        impulse = sum((b[0] - a[0]) * (a[1] + b[1]) / 2 for a, b in zip(motor.curve, motor.curve[1:]))
        return {"review_token": token, "motor": motor.model_dump(), "provenance": provenance,
                "summary": {"total_impulse_ns": impulse, "burn_time_s": motor.curve[-1][0],
                    "max_thrust_n": max(point[1] for point in motor.curve), "samples": len(motor.curve)},
                "warnings": ["Provider source is reported as supplied. Confirm designation, dimensions, mass, hardware, and curve applicability before assigning it to a flight configuration.",
                             "Burn time shown is the final curve time; total impulse is integrated from the downloaded samples. Recovery ejection delays are not assigned automatically."]}

    def reviewed_motor(self, token: str) -> Motor:
        with self._lock:
            self._prune(self._reviews)
            item = self._reviews.get(token)
            if item is None:
                raise ValueError("Motor review expired or is unknown. Preview the selected curve again before importing.")
            return item[1].model_copy(deep=True)
