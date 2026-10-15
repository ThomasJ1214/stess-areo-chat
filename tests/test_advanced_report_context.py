"""Actual advanced flight metadata must survive the user-facing export paths."""
import csv
import io
import json

from fastapi.testclient import TestClient

from rocket_workbench.api import create_app
from rocket_workbench.demo import demo_project
from rocket_workbench.jobs import compare
from rocket_workbench.models import Conditions
from rocket_workbench.reports import render_report
from test_api import wait


def test_actual_dynamic_flight_report_and_csv_keep_coverage_and_integration():
    with TestClient(create_app()) as client:
        assert client.put('/api/project', json=demo_project().model_dump()).status_code == 200
        submitted = client.post('/api/jobs', json={"kind": "flight", "conditions": {
            "flight_model": "rigid_body", "wind_model": "dryden", "max_time": 1,
            "dt": .05, "wind_speed": .2}, "options": {"structural_mode": "dynamic_fins",
            "elements": 4, "allow_isotropic_surrogate": True}}).json()
        job = wait(client, submitted['id'])
        assert job['status'] == 'completed', job.get('error')
        result = job['result']
        assert result['dynamic_structural_analysis']['components'][0]['time_integrator'] == 'exact_foh'
        response = client.get(f"/api/jobs/{job['id']}/export?format=csv")
        assert response.status_code == 200
        rows = list(csv.DictReader(io.StringIO(response.text)))
        for name in ('wind', 'inertia', 'numerical_integration', 'dynamic_structural_analysis'):
            assert json.loads(rows[0]['_result_'+name]) == result[name]
            assert all(not row.get('_result_'+name) for row in rows[1:])
        report = client.get(f"/api/jobs/{job['id']}/export?format=html").text
        for phrase in ('Wind realization', 'Inertia and mass-distribution', 'Dynamic fin model, coverage', 'exact_foh', 'Dynamic fin beam stress'):
            assert phrase in report


def test_actual_laminar_comparison_and_report_use_actual_child_methods():
    result = compare(demo_project(), Conditions(speed=100, wind_speed=0), None,
                     {'use_cfd': True, 'physics_model': 'laminar', 'mode': 'transient',
                      'transient_source': 'fixed', 'duration_s': .0001, 'backend': 'cpu',
                      'grid_resolution': 12, 'transverse_resolution': 12, 'max_cells': 50000},
                     None, lambda: False)
    assert 'laminar' in result['fidelity']
    assert 'inviscid Euler geometry comparison' not in result['fidelity']
    assert 'numpy-cpu' in result['backend']
    html = render_report('comparison', result)
    assert 'Total force n' in html and 'Viscous force n' in html
