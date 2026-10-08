"""Offline engineering reports with bounded, actual-data SVG plots.

Reports preserve method limits and run provenance, but deliberately omit large
solved fields. JSON/CSV exports remain the source for full-resolution data.
"""
from __future__ import annotations

import html
import json
import math
from collections.abc import Mapping


MAX_PLOT_POINTS = 400
MAX_TABLE_ROWS = 80

_LABELS = {
    "speed": "Primary airspeed (m/s)", "mach": "Mach (dimensionless)",
    "altitude": "Altitude MSL (m)", "angle_of_attack": "Angle of attack (deg)",
    "sideslip": "Sideslip (deg)", "wind_speed": "Wind speed (m/s)",
    "wind_direction": "Wind toward direction (deg)", "turbulence": "Gust intensity (dimensionless)",
    "temperature_delta": "Temperature offset (K)", "rail_length": "Rail length (m)",
    "launch_angle": "Launch angle from vertical (deg)", "launch_azimuth": "Launch azimuth (deg)",
    "dt": "Maximum integration time step (s)", "max_time": "Maximum integration time (s)",
    "project_sha256": "Run input project SHA-256", "geometry_signature": "Geometry SHA-256",
    "application_version": "Application version", "submitted_at": "Submitted at (UTC)",
    "apogee_m": "Apogee AGL (m)", "max_velocity_m_s": "Maximum velocity (m/s)",
    "max_mach": "Maximum Mach (dimensionless)", "max_dynamic_pressure_pa": "Maximum dynamic pressure (Pa)",
    "max_acceleration_m_s2": "Maximum inertial acceleration (m/s²)",
    "max_stress_pa": "Maximum estimated stress (Pa)", "flight_time_s": "Flight time (s)",
    "mass_kg": "Mass (kg)", "cg_m": "Axial CG (m)", "cp_m": "Axial CP (m)",
    "stability_calibers": "Static margin (calibers)", "cd": "Drag coefficient (dimensionless)",
    "drag_n": "Drag (N)", "normal_force_n": "Normal force (N)",
    "dynamic_pressure_pa": "Dynamic pressure (Pa)", "volume_m3": "Material volume (m³)",
    "max_displacement_m": "Maximum displacement (m)", "max_von_mises_pa": "Peak element von Mises stress (Pa)",
    "stress_pa": "Estimated stress (Pa)", "deflection_m": "Estimated local deflection (m)",
    "safety_factor": "Supplied strength / predicted stress (dimensionless)",
    "load_n": "Lateral resultant (N)", "time_s": "Time (s)",
}


def _escape(value) -> str:
    return html.escape(str(value), quote=True)


def _label(key) -> str:
    return _LABELS.get(str(key), str(key).replace("_", " ").capitalize())


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _formatted(value) -> str:
    if value is None:
        return "Unavailable"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if _number(value):
        if value == 0:
            return "0"
        return f"{value:.6g}"
    if isinstance(value, (int, float)):
        return "Unavailable (nonfinite)"
    return str(value)


def _bounded(value, depth=0):
    """Keep nested summary/input objects useful without dumping field arrays."""
    if isinstance(value, Mapping):
        if depth >= 4:
            return f"Object with {len(value)} entries; full data in JSON export"
        selected = list(value.items())[:40]
        output = {str(key): _bounded(item, depth + 1) for key, item in selected}
        if len(value) > 40:
            output["omitted_entries"] = len(value) - 40
        return output
    if isinstance(value, (list, tuple)):
        if depth >= 4:
            return f"Array of {len(value)} entries; full data in JSON export"
        output = [_bounded(item, depth + 1) for item in value[:12]]
        if len(value) > 12:
            output.append(f"{len(value) - 12} further entries omitted")
        return output
    if isinstance(value, float) and not math.isfinite(value):
        return "Unavailable (nonfinite)"
    return value


def _cell(value) -> str:
    if isinstance(value, (Mapping, list, tuple)):
        return "<pre>" + _escape(json.dumps(_bounded(value), indent=2, ensure_ascii=False)) + "</pre>"
    return _escape(_formatted(value))


def _pairs(values) -> str:
    if not isinstance(values, Mapping) or not values:
        return '<p class="muted">No values available.</p>'
    rows = "".join(f"<tr><th scope=\"row\">{_escape(_label(key))}</th><td>{_cell(value)}</td></tr>"
                   for key, value in list(values.items())[:160])
    if len(values) > 160:
        rows += '<tr><td colspan="2">Additional entries are available in the JSON export.</td></tr>'
    return '<div class="table-wrap"><table class="pairs"><tbody>' + rows + "</tbody></table></div>"


def _table(rows, fields=None) -> str:
    rows = [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []
    if not rows:
        return '<p class="muted">No rows available.</p>'
    available_fields = list(dict.fromkeys(key for row in rows[:MAX_TABLE_ROWS] for key in row))
    fields = fields or available_fields[:18]
    body = "".join("<tr>" + "".join(f"<td>{_cell(row.get(field))}</td>" for field in fields) + "</tr>"
                   for row in rows[:MAX_TABLE_ROWS])
    headers = "".join(f'<th scope="col">{_escape(_label(field))}</th>' for field in fields)
    note = (f'<p class="muted">Showing {MAX_TABLE_ROWS} of {len(rows)} rows. Full data is available in JSON/CSV.</p>'
            if len(rows) > MAX_TABLE_ROWS else "")
    omitted = len(set(available_fields) - set(fields))
    if omitted:
        note += f'<p class="muted">{omitted} additional columns are available in the JSON/CSV export.</p>'
    return '<div class="table-wrap"><table><thead><tr>' + headers + "</tr></thead><tbody>" + body + "</tbody></table></div>" + note


def _section(title, content) -> str:
    return f"<section><h2>{_escape(title)}</h2>{content}</section>"


def _method_context(result) -> str:
    """Keep every displayed solver's actual fidelity and warnings visible."""
    output = '<div class="method"><strong>Calculation method</strong><p>'
    output += _escape(result.get("fidelity", "Method unavailable"))
    output += "</p><p><strong>Actual backend:</strong> "
    output += _escape(result.get("backend", "Unavailable")) + "</p></div>"
    warnings = result.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        output += '<ul class="warnings">' + "".join(f"<li>{_escape(warning)}</li>" for warning in warnings) + "</ul>"
    if result.get("validity"):
        output += "<h3>Validity flags</h3>" + _pairs(result["validity"])
    return output


def _structural_content(result) -> str:
    rows = []
    for row in result.get("components", []):
        if not isinstance(row, Mapping):
            continue
        row = dict(row)
        # Unsupported reference/CAD parts carry placeholder zeroes in the raw
        # fast-model result. They must never appear as solved zero stress.
        if row.get("supported") is not True:
            for field in ("stress_pa", "deflection_m", "safety_factor"):
                row[field] = None
        rows.append(row)
    return _method_context(result) + _table(rows, ["name", "material", "supported", "stress_pa",
        "deflection_m", "safety_factor", "fidelity", "warnings"])


def _cfd_content(result) -> str:
    output = _pairs(result.get("summary", {}))
    history = result.get("history", [])
    if history:
        output += "<h3>Recorded convergence history</h3>"
        for key, title in (("residual", "Fluid steady residual"),
                           ("wall_pressure_residual", "Wall-pressure steady residual"),
                           ("force_residual", "Resultant-force steady residual"),
                           ("moment_residual", "Centered-moment steady residual")):
            if any(isinstance(row, Mapping) and key in row for row in history):
                output += _plot(history, "step", key, title,
                    "Solver iteration (count)", "Residual (dimensionless)")
    return output


def _sample_segment(segment, budget):
    if len(segment) <= budget:
        return segment
    if budget <= 2:
        return [segment[0], segment[-1]][:budget]
    # Keep endpoints and both local extrema in each bucket. Every selected point
    # comes directly from a solver row; no interpolated measurement is created.
    buckets = (budget - 2) // 2
    selected = {0, len(segment) - 1}
    for index in range(buckets):
        start = 1 + index * (len(segment) - 2) // buckets
        stop = 1 + (index + 1) * (len(segment) - 2) // buckets
        if stop > start:
            selected.add(min(range(start, stop), key=lambda i: segment[i][1]))
            selected.add(max(range(start, stop), key=lambda i: segment[i][1]))
    return [segment[index] for index in sorted(selected)]


def _plot(rows, x_key, y_key, title, x_label, y_label) -> str:
    segments, current = [], []
    for row in rows if isinstance(rows, list) else []:
        x, y = (row.get(x_key), row.get(y_key)) if isinstance(row, Mapping) else (None, None)
        if _number(x) and _number(y):
            current.append((float(x), float(y)))
        elif current:
            segments.append(current)
            current = []
    if current:
        segments.append(current)
    points = [point for segment in segments for point in segment]
    if not points:
        return f'<figure><figcaption>{_escape(title)}</figcaption><p class="muted">Unavailable: no finite recorded samples.</p></figure>'
    x_min, x_max = min(point[0] for point in points), max(point[0] for point in points)
    y_min, y_max = min(point[1] for point in points), max(point[1] for point in points)
    if x_min == x_max:
        x_min, x_max = x_min - .5, x_max + .5
    if y_min == y_max:
        margin = abs(y_min) * .05 or .5
        y_min, y_max = y_min - margin, y_max + margin
    # Pathological null-separated fields can have more segments than the entire
    # plotting budget. Select evenly spaced segments, retaining explicit gaps.
    if len(segments) > MAX_PLOT_POINTS // 4:
        last = len(segments) - 1
        indices = sorted({round(i * last / (MAX_PLOT_POINTS // 4 - 1)) for i in range(MAX_PLOT_POINTS // 4)})
        segments = [segments[index] for index in indices]
    budget = MAX_PLOT_POINTS // len(segments)
    plotted = [_sample_segment(segment, budget) for segment in segments]
    count = sum(len(segment) for segment in plotted)
    width, height = 720, 270
    left, right, top, bottom = 88, 18, 18, 54
    plot_width, plot_height = width - left - right, height - top - bottom

    def position(point):
        return (left + (point[0] - x_min) / (x_max - x_min) * plot_width,
                top + (y_max - point[1]) / (y_max - y_min) * plot_height)

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{_escape(title)}">',
           f"<title>{_escape(title)} — recorded solver data</title>"]
    for i in range(5):
        fraction = i / 4
        xx, yy = left + fraction * plot_width, top + fraction * plot_height
        svg.append(f'<path d="M{left} {yy:.2f}H{width-right}" class="grid"/>')
        svg.append(f'<text x="{left-8}" y="{yy+4:.2f}" text-anchor="end">{_escape(_formatted(y_max - fraction * (y_max-y_min)))}</text>')
        svg.append(f'<text x="{xx:.2f}" y="{height-bottom+22}" text-anchor="middle">{_escape(_formatted(x_min + fraction * (x_max-x_min)))}</text>')
    for segment in plotted:
        coordinates = " ".join(f"{x:.3f},{y:.3f}" for x, y in map(position, segment))
        if len(segment) > 1:
            svg.append(f'<polyline points="{coordinates}" class="data"/>')
        else:
            x, y = position(segment[0])
            svg.append(f'<circle cx="{x:.3f}" cy="{y:.3f}" r="3" class="point"/>')
    svg.append(f'<text x="{left+plot_width/2}" y="{height-9}" text-anchor="middle">{_escape(x_label)}</text>')
    svg.append(f'<text x="18" y="{top+plot_height/2}" transform="rotate(-90 18 {top+plot_height/2})" text-anchor="middle">{_escape(y_label)}</text></svg>')
    note = f"Showing {count} of {len(points)} finite recorded samples."
    if count < len(points):
        note += " Downsampling retains local extrema where the plotting budget permits."
    note += " Lines connect retained samples; missing values remain gaps."
    return f'<figure><figcaption>{_escape(title)}</figcaption>' + "".join(svg) + f'<p class="muted">{_escape(note)}</p></figure>'


def _flight_content(result) -> str:
    output = _pairs(result.get("summary", {}))
    if result.get("events"):
        events = [{"event": row.get("name"), "time_s": row.get("time"), "sample_index": row.get("index")}
                  for row in result["events"] if isinstance(row, Mapping)]
        output += "<h3>Recorded flight events</h3>" + _table(events)
    rows = result.get("trajectory", [])
    if rows:
        output += _plot(rows, "time", "altitude", "Altitude above launch level", "Time (s)", "Altitude AGL (m)")
        output += _plot(rows, "time", "dynamic_pressure", "Dynamic pressure", "Time (s)", "Dynamic pressure (Pa)")
        for key, title, label in (("velocity", "Velocity", "Velocity (m/s)"),
                                  ("acceleration", "Inertial acceleration magnitude", "Acceleration (m/s²)"),
                                  ("mach", "Mach", "Mach (dimensionless)"),
                                  ("stability", "Instantaneous static margin", "Static margin (calibers)")):
            if any(isinstance(row, Mapping) and key in row for row in rows):
                output += _plot(rows, "time", key, title, "Time (s)", label)
        if any(isinstance(row, Mapping) and _number(row.get("stress")) for row in rows):
            output += _plot(rows, "time", "stress", "Quasi-static stress estimate", "Time (s)", "Estimated stress (Pa)")
        elif any(isinstance(row, Mapping) and "stress" in row for row in rows):
            output += '<p class="muted">Flight stress estimate: Unavailable; no finite stress field was recorded.</p>'
    return output


def render_report(kind: str, result: dict) -> str:
    """Render a readable, escaped standalone HTML report from an actual result."""
    inputs = result.get("inputs", {})
    project_name = inputs.get("project_name", "Rocket project") if isinstance(inputs, Mapping) else "Rocket project"
    title = f"{project_name} · {str(kind).replace('_', ' ').title()} report"
    style = """body{font:15px/1.5 system-ui,sans-serif;color:#182b3c;background:#f0f4f7;margin:0}
main{max-width:1050px;margin:32px auto;padding:32px;background:white;border-radius:14px}
h1{font-size:30px;line-height:1.2}h2{font-size:22px;margin:0 0 16px}h3{margin-top:24px}
section{margin-top:32px;padding-top:24px;border-top:1px solid #d7e0e6}.muted{color:#536575;font-size:13px}
.method{padding:16px;background:#edf5fb;border-left:4px solid #2f718b}.warnings{padding:16px 32px;background:#fff7e7}
.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:9px 12px;border-bottom:1px solid #e2e8ed;text-align:left;vertical-align:top}
thead th{background:#edf2f6}.pairs th{width:36%;font-weight:500}pre{font:12px/1.4 ui-monospace,monospace;white-space:pre-wrap;overflow-wrap:anywhere;margin:0}
figure{margin:24px 0}figcaption{font-weight:600;margin-bottom:8px}svg{width:100%;height:auto;background:#f8fafc}
svg text{font:11px system-ui,sans-serif;fill:#45586b}.grid{stroke:#dce5ec;stroke-width:1}.data{fill:none;stroke:#186b8c;stroke-width:2}.point{fill:#186b8c}
@media print{body{background:white}main{margin:0;padding:0}section,figure{break-inside:avoid}pre{font-size:10px}}
"""
    body = f"<h1>{_escape(title)}</h1><p>Rocket Workbench engineering report</p>"
    body += '<p class="muted">Quantities are SI; angles are degrees and coefficients are dimensionless unless specified. A completed calculation does not establish physical validation.</p>'
    body += '<div class="method"><strong>Calculation method</strong><p>' + _escape(result.get("fidelity", "Method unavailable"))
    body += "</p><p><strong>Actual backend:</strong> " + _escape(result.get("backend", "Unavailable")) + "</p></div>"
    warnings = result.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        body += _section("Warnings and interpretation limits", '<ul class="warnings">' + "".join(f"<li>{_escape(warning)}</li>" for warning in warnings) + "</ul>")
    else:
        body += '<p class="muted">No warnings were recorded. This does not imply independent validation.</p>'
    if result.get("validity"):
        body += _section("Validity flags", _pairs(result["validity"]))
    if result.get("conventions"):
        body += _section("Coordinate and result conventions", _pairs(result["conventions"]))
    if kind == "flight":
        body += _section("Flight results", _flight_content(result))
    elif kind == "comparison":
        for basis in ("original", "replacement"):
            data = result.get(basis, {})
            if not isinstance(data, Mapping):
                continue
            content = ""
            if isinstance(data.get("aero"), Mapping):
                aero = data["aero"]
                content += "<h3>Fast aerodynamic and mass results</h3>" + _pairs({k: aero[k] for k in _LABELS if k in aero})
                content += _method_context(aero)
            if isinstance(data.get("structure"), Mapping):
                content += "<h3>Structural estimates</h3>" + _structural_content(data["structure"])
            if isinstance(data.get("flight"), Mapping):
                content += "<h3>Flight</h3>" + _method_context(data["flight"]) + _flight_content(data["flight"])
            if data.get("flight_error"):
                content += '<p class="warnings">Flight unavailable: ' + _escape(data["flight_error"]) + "</p>"
            if isinstance(data.get("cfd"), Mapping):
                content += "<h3>CFD</h3>" + _method_context(data["cfd"]) + _cfd_content(data["cfd"])
            body += _section("Original OpenRocket geometry" if basis == "original" else "Current replacement geometry", content)
        body += _section("Current minus original differences", _pairs(result.get("deltas", {})))
        if result.get("flight_deltas"):
            body += _section("Flight differences: current minus original", _pairs(result["flight_deltas"]))
        if result.get("configurations"):
            configuration_rows = []
            for row in result["configurations"]:
                if not isinstance(row, Mapping):
                    continue
                aero = row.get("aero") or {}
                configuration_rows.append({"configuration": row.get("name"), "mass_kg": aero.get("mass_kg"),
                    "cg_m": aero.get("cg_m"), "cp_m": aero.get("cp_m"), "stability_calibers": aero.get("stability_calibers"),
                    "fidelity": aero.get("fidelity"), "warnings": aero.get("warnings"), "error": row.get("error")})
            body += _section("Configuration comparison", _table(configuration_rows))
    elif kind in {"sweep", "monte_carlo"}:
        body += _section("Study setup", _pairs({key: result[key] for key in ["parameter", "seed", "gust_seed_policy"] if key in result}))
        body += _section("Statistics from successful samples", _pairs(result.get("statistics", {})))
        body += _section("Recorded study samples", _table(result.get("rows", [])))
        if result.get("failures"):
            body += _section("Excluded failed samples", _table(result["failures"]))
    else:
        body += _section("Calculation summary", _cfd_content(result) if kind == "cfd" else _pairs(result.get("summary", {})))
    if isinstance(inputs, Mapping) and inputs:
        provenance = {key: value for key, value in inputs.items() if key not in {"conditions", "options"}}
        body += _section("Run identity and source provenance", _pairs(provenance))
        body += _section("Conditions used for this run", _pairs(inputs.get("conditions", {})))
        body += _section("Solver options used for this run", _pairs(inputs.get("options", {})))
    else:
        body += _section("Run provenance", '<p class="muted">Run inputs were not recorded in this result.</p>')
    body += _section("Full-resolution data", '<p>This report omits large mesh, pressure, displacement and trajectory arrays. Export simulation JSON/CSV for full-resolution fields and retain the run input project to reproduce its geometry, materials and settings.</p>')
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' + f"<title>{_escape(title)}</title><style>{style}</style></head><body><main>{body}</main></body></html>"
