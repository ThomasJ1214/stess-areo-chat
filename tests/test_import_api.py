"""Import workflows through HTTP, including persistent CAD and honest polars."""
from pathlib import Path

from fastapi.testclient import TestClient
import numpy as np
import pytest
import trimesh

from rocket_workbench.api import create_app
from rocket_workbench.models import Project


def import_box(client, dimensions=(.4,.1,.1)):
    box=trimesh.creation.box(dimensions)
    result=client.post('/api/import/geometry',data={'units':'m'},
        files={'file':('actual-payload.stl',box.export(file_type='stl'))})
    assert result.status_code==200,result.text
    return result.json()


def test_cad_replacement_project_roundtrip_and_physical_bounds(tmp_path):
    with TestClient(create_app(data_dir=tmp_path)) as client:
        asset=import_box(client)
        attached=client.post('/api/geometry/attach',json={
            'component_id':'payload','asset_id':asset['id'],
            'transform':{'translation':[.1,.02,0],'rotation':[0,0,0],'scale':1.5}})
        assert attached.status_code==200,attached.text
        properties=client.get('/api/geometry/properties/payload').json()
        assert properties['replacement']['volume_m3']==pytest.approx(.4*.1*.1*1.5**3)
        assert properties['replacement']['bounds_m'][0][0]==pytest.approx(.45+.1-.4*1.5/2)
        assert properties['original']['bounds_m'][0][0]==pytest.approx(.45)
        downloaded=client.get('/api/project/download')
        value=Project.model_validate_json(downloaded.content)
        assert np.ptp(np.asarray(value.assets[0].vertices),axis=0)==pytest.approx([.4,.1,.1])
        result=client.post('/api/project/load',files={'file':('saved.rocket.json',downloaded.content)})
        assert result.status_code==200,result.text
        after=client.get('/api/geometry/properties/payload').json()
        assert after==properties
    with TestClient(create_app(data_dir=tmp_path)) as restored:
        assert restored.get('/api/project').json()['assets'][0]['id']==asset['id']
        assert restored.get('/api/geometry/properties/payload').json()==properties


def test_standalone_cad_requires_explicit_polar_for_cp_then_uses_real_coefficients():
    with TestClient(create_app()) as client:
        asset=import_box(client)
        result=client.post('/api/geometry/standalone',json={'asset_id':asset['id']})
        assert result.status_code==200,result.text
        project=result.json()
        assert project['metadata']['cad_only']
        assert len(project['components'])==1
        component=project['components'][0]
        assert component['geometry_mode']=='replacement'
        assert component['transform']['translation'][0]==pytest.approx(.2)
        assert project['configurations'][0]['motor_id'] is None
        bare=client.post('/api/analyze',json={'conditions':{'mach':.5,'wind_speed':0}})
        assert bare.status_code==200,bare.text
        assert bare.json()['aero']['cp_m'] is None
        assert bare.json()['aero']['stability_calibers'] is None
        polar=b'mach,cd,cna,cp_m,source\n0,0.4,2,0.3,benchmarked-source\n2,0.8,3,0.32,benchmarked-source\n'
        imported=client.post('/api/import/polar',files={'file':('coefficients.csv',polar)})
        assert imported.status_code==200,imported.text
        analyzed=client.post('/api/analyze',json={'conditions':{'mach':.5,'wind_speed':0}})
        assert analyzed.status_code==200,analyzed.text
        aero=analyzed.json()['aero']
        assert aero['cd']==pytest.approx(.5)
        assert aero['cp_m']==pytest.approx(.305)
        assert aero['mass_kg']==pytest.approx(.4*.1*.1*1850)
        # Geometry-specific polar must stop applying after a CAD alignment change.
        update=client.get('/api/project').json()
        update['components'][0]['transform']['scale']=1.1
        assert client.put('/api/project',json=update).status_code==200
        stale=client.post('/api/analyze',json={'conditions':{'mach':.5,'wind_speed':0}})
        assert stale.status_code==200,stale.text
        assert stale.json()['aero']['cp_m'] is None
        assert any('stale' in warning for warning in stale.json()['aero']['warnings'])


def test_zero_cna_polar_is_rejected_without_replacing_valid_project():
    with TestClient(create_app()) as client:
        before=client.get('/api/project').json()
        result=client.post('/api/import/polar',files={'file':('zero.csv',
            b'mach,cd,cna,cp_m\n0,.4,0,.3\n2,.8,0,.3\n')})
        assert result.status_code==400,result.text
        assert client.get('/api/project').json()==before


def test_saved_invalid_face_indices_are_rejected_before_viewer():
    with TestClient(create_app()) as client:
        asset=import_box(client)
        client.post('/api/geometry/attach',json={'component_id':'payload','asset_id':asset['id']})
        good=client.get('/api/project').json()
        bad=client.get('/api/project').json()
        bad['assets'][0]['faces'][0]=[10_000_000,10_000_001,10_000_002]
        result=client.put('/api/project',json=bad)
        assert result.status_code==422,result.text
        assert client.get('/api/project').json()==good
        assert client.get('/api/mesh').status_code==200


def test_comparison_retains_valid_configuration_when_other_has_no_active_stage():
    with TestClient(create_app()) as client:
        value=client.get('/api/project').json()
        value['configurations'][1]['active_component_ids']=[]
        assert client.put('/api/project',json=value).status_code==200
        result=client.post('/api/compare',json={'conditions':{}})
        assert result.status_code==200,result.text
        answer=result.json()
        assert answer['original']['aero']['mass_kg']>0
        empty=next(row for row in answer['configurations'] if row['configuration_id']=='single')
        assert empty.get('error')
        valid=next(row for row in answer['configurations'] if row['configuration_id']=='dual')
        assert valid['aero']['mass_kg']>0


def test_real_ork_http_import_configuration_selection_mesh_and_download():
    fixture=Path(__file__).parent/'fixtures/openrocket/dual-deployment.ork'
    with TestClient(create_app()) as client:
        result=client.post('/api/import/ork',files={'file':('dual.ork',fixture.read_bytes())})
        assert result.status_code==200,result.text
        project=result.json()
        assert len(project['configurations'])==6
        assert project['active_configuration_id']=='098d8c95-54c4-4552-bf81-e65e1de4796b'
        assert project['metadata']['motor_assignments'][3]['designation']=='H999N'
        assert all(cfg['motor_id'] is None for cfg in project['configurations'])
        project['active_configuration_id']=project['configurations'][0]['id']
        assert client.put('/api/project',json=project).status_code==200
        response=client.get('/api/mesh')
        assert response.status_code==200,response.text
        assert any(c['faces'] for c in response.json()['components'])
        saved=Project.model_validate_json(client.get('/api/project/download').content)
        assert saved.active_configuration_id==project['configurations'][0]['id']
        assert saved.configurations[0].main_deploy_altitude==152.4


def test_missing_cfd_pressure_source_is_a_client_error():
    with TestClient(create_app()) as client:
        result=client.post('/api/jobs',json={'kind':'fea','options':{
            'component_id':'payload','load_mode':'cfd_pressure','cfd_job_id':'missing'}})
        assert result.status_code==400,result.text
