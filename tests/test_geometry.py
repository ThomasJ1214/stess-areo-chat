import math
from pathlib import Path

import numpy as np
import pytest
import trimesh

from rocket_workbench.geometry import component_mesh, geometry_properties, import_geometry, project_mesh
from rocket_workbench.imports import import_ork
from rocket_workbench.models import Component, GeometryAsset, Project, Transform


def test_hollow_tube_has_wall_volume_and_closed_ends():
    c = Component(length=1, radius=.05, thickness=.002)
    m = component_mesh(Project(), c)
    expected = math.pi * (.05 ** 2 - .048 ** 2)
    assert m.is_watertight
    assert m.volume == pytest.approx(expected, rel=.002)
    assert m.bounds[:, 0].tolist() == [0, 1]


@pytest.mark.parametrize("kind", ['nosecone','transition','bodytube','innertube','bulkhead',
    'trapezoidfinset','ellipticalfinset','freeformfinset'])
def test_supported_original_parts_have_positive_watertight_volume(kind):
    c = Component(kind=kind, length=.3, radius=.05, radius_end=.03, thickness=.003,
        metadata={'fin_points':[[0,0],[.04,.10],[.12,.08],[.3,0]], 'nose_shape':'ogive','shape_parameter':1})
    m = component_mesh(Project(), c)
    assert m.is_watertight
    assert m.volume > 0
    assert np.isfinite(m.vertices).all()


def test_ring_inner_radius_and_filled_body():
    p = Project()
    c = Component(kind='centeringring', length=.01, radius=.05, metadata={'inner_radius':.02})
    m = component_mesh(p,c)
    assert m.volume == pytest.approx(math.pi * (.05 ** 2 - .02 ** 2) * .01, rel=.002)
    solid = c.model_copy(update={'kind':'bodytube','metadata':{'filled':True}})
    assert component_mesh(p,solid).volume == pytest.approx(math.pi * .05**2 * .01, rel=.002)


def test_three_fin_prisms_match_analytic_volume():
    c = Component(kind='trapezoidfinset', fin_count=3, root_chord=.3,
        tip_chord=.1,span=.2,thickness=.004,radius=.05)
    m = component_mesh(Project(), c)
    assert m.volume == pytest.approx(3 * (.3+.1)/2 * .2 * .004)
    assert len(m.split()) == 3


def test_freeform_concave_polygon_preserved():
    points = [[0,0],[.1,.2],[.2,.2],[.15,.1],[.3,0]]
    c = Component(kind='freeformfinset',fin_count=1,thickness=.005,metadata={'fin_points':points})
    m = component_mesh(Project(),c)
    arr=np.asarray(points)
    area=abs(np.sum(arr[:,0]*np.roll(arr[:,1],-1)-np.roll(arr[:,0],-1)*arr[:,1])/2)
    assert m.volume == pytest.approx(area*.005)
    assert m.is_watertight


@pytest.mark.parametrize('shape,parameter', [('conical',0),('ogive',1),('ogive',.5),('ellipsoid',0),
    ('haack',0),('haack',1/3),('parabolic',1),('power',.5)])
def test_nose_profiles_contain_true_tip_base_and_closed_shell(shape,parameter):
    c=Component(kind='nosecone',length=.5,radius=.05,metadata={'nose_shape':shape,'shape_parameter':parameter})
    m=component_mesh(Project(),c)
    assert m.bounds[0,0] == 0
    assert m.bounds[1,0] == .5
    assert m.bounds[1,1] == pytest.approx(.05)
    assert m.is_watertight
    tip=m.vertices[np.abs(m.vertices[:,0])<1e-12]
    assert np.max(np.abs(tip[:,1:])) < 1e-7


def test_clipped_transition_endpoints_match_radii():
    c=Component(kind='transition',length=.2,radius=.02,radius_end=.05,
        metadata={'nose_shape':'haack','shape_parameter':0,'shape_clipped':True})
    m=component_mesh(Project(),c)
    for x, radius in [(0,.02),(.2,.05)]:
        ring=m.vertices[np.isclose(m.vertices[:,0],x)]
        assert np.linalg.norm(ring[:,1:],axis=1).max()==pytest.approx(radius)
    assert m.is_watertight


@pytest.mark.parametrize('suffix', ['stl','obj','ply'])
def test_mesh_format_and_unit_conversion(suffix):
    m=trimesh.creation.box([10,20,30])
    data=m.export(file_type=suffix)
    if isinstance(data,str):data=data.encode()
    asset=import_geometry(data,'box.'+suffix,'mm')
    assert asset.watertight
    assert asset.volume==pytest.approx(.01*.02*.03,rel=.001)
    assert np.ptp(np.asarray(asset.vertices),axis=0)==pytest.approx([.01,.02,.03])
    assert asset.source_file=='box.'+suffix


def test_step_occt_real_solid_and_embedded_units(tmp_path):
    pytest.importorskip('OCP')
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
    path=tmp_path/'box.step'
    writer=STEPControl_Writer()
    writer.Transfer(BRepPrimAPI_MakeBox(10,20,30).Shape(),STEPControl_AsIs)
    assert writer.Write(str(path))==IFSelect_RetDone
    a=import_geometry(path.read_bytes(),'box.step','in')
    assert a.volume==pytest.approx(.01*.02*.03,rel=1e-5)
    assert a.watertight
    assert any('units are read' in w for w in a.warnings)


def test_open_surface_is_not_solid_mass():
    m=trimesh.creation.box([1,1,1])
    m.update_faces(np.arange(len(m.faces)) != 0)
    a=import_geometry(m.export(file_type='stl'),'surface.stl','m')
    assert not a.watertight
    assert a.volume==0
    assert any('volume is unknown' in w for w in a.warnings)


def test_replacement_alignment_origin_scale_and_comparison():
    m=trimesh.creation.box([.1,.2,.3])
    a=GeometryAsset(name='real payload',format='stl',vertices=m.vertices.tolist(),faces=m.faces.tolist(),watertight=True,volume=float(m.volume))
    c=Component(x=1,length=.4,radius=.05,asset_id=a.id,geometry_mode='replacement',
        transform=Transform(translation=[.2,.3,.4],rotation=[0,0,90],scale=2))
    p=Project(assets=[a],components=[c])
    actual=component_mesh(p,c)
    assert actual.center_mass==pytest.approx([1.2,.3,.4])
    assert actual.extents==pytest.approx([.4,.2,.6])
    assert actual.volume==pytest.approx(m.volume*8)
    original=component_mesh(p,c,original=True)
    assert original.bounds[:,0]==pytest.approx([1,1.4])
    assert original.center_mass[1:]==pytest.approx([0,0],abs=1e-10)
    assert geometry_properties(p,c)['volume_m3']==pytest.approx(m.volume*8)


def test_project_external_geometry_and_real_fixture():
    fixture=Path(__file__).parent/'fixtures/openrocket/dual-deployment.ork'
    p=import_ork(fixture.read_bytes(),fixture.name)
    mesh=project_mesh(p)
    assert mesh.is_watertight
    assert mesh.volume > 0
    assert mesh.bounds[1,0] > 1
    assert all(component_mesh(p,c).is_watertight for c in p.components if len(component_mesh(p,c).faces))


@pytest.mark.parametrize('data,name,units',[(b'bad','bad.step','mm'),(b'bad','bad.stl','mm'),
    (b'v 0 0 0\nv 0 nan 1\nv 1 0 0\nf 1 2 3','bad.obj','m'),
    (b'bad','bad.dwg','mm'),(b'bad','bad.stl','yards')])
def test_bad_cad_input_rejected(data,name,units):
    with pytest.raises(ValueError):import_geometry(data,name,units)


def test_missing_replacement_asset_rejected():
    with pytest.raises(ValueError,match='missing'):
        component_mesh(Project(),Component(geometry_mode='replacement',asset_id='absent'))


def test_nested_cavity_volume_is_subtracted_not_flipped_to_material():
    from rocket_workbench.geometry import _validate_mesh
    outer=trimesh.creation.icosphere(subdivisions=1,radius=.05)
    inner=trimesh.creation.icosphere(subdivisions=1,radius=.04)
    inner.invert()
    hollow=trimesh.util.concatenate([outer,inner])
    expected=float(hollow.volume)
    repaired=_validate_mesh(hollow.copy())
    assert repaired.volume==pytest.approx(expected)
    asset=import_geometry(hollow.export(file_type='stl'),'cavity.stl','m')
    assert asset.volume==pytest.approx(expected,rel=1e-6)
    assert asset.watertight
    assert any('cavity volume is subtracted' in w for w in asset.warnings)
    # Winding correction also handles a completely inside-out boundary mesh.
    hollow.invert()
    asset=import_geometry(hollow.export(file_type='stl'),'reversed-cavity.stl','m')
    assert asset.volume==pytest.approx(expected,rel=1e-6)


def test_disjoint_closed_parts_are_additive_not_cavities():
    a=trimesh.creation.box([.1,.1,.1]);b=a.copy();b.apply_translation([.3,0,0]);b.invert()
    asset=import_geometry(trimesh.util.concatenate([a,b]).export(file_type='stl'),'assembly.stl','m')
    assert asset.watertight
    assert asset.volume==pytest.approx(.002,rel=1e-6)


def test_step_preserves_actual_internal_cavity(tmp_path):
    pytest.importorskip('OCP')
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
    outer=BRepPrimAPI_MakeBox(10,20,30).Shape()
    cavity=BRepPrimAPI_MakeBox(gp_Pnt(1,1,1),8,18,28).Shape()
    hollow=BRepAlgoAPI_Cut(outer,cavity).Shape()
    path=tmp_path/'hollow.step';writer=STEPControl_Writer()
    writer.Transfer(hollow,STEPControl_AsIs)
    assert writer.Write(str(path))==IFSelect_RetDone
    asset=import_geometry(path.read_bytes(),'hollow.step')
    assert asset.watertight
    assert asset.volume==pytest.approx((10*20*30-8*18*28)*1e-9,rel=1e-6)


def test_zero_thickness_source_renders_surface_without_wall_material():
    c=Component(length=.3,radius=.05,thickness=0,mass_override=0,metadata={'zero_thickness':True})
    m=component_mesh(Project(),c)
    assert len(m.faces)>0
    assert not m.is_watertight
    assert m.bounds[:,0]==pytest.approx([0,.3])


def test_canonical_profile_matches_mesh_shape_and_flipped_nose():
    from rocket_workbench.geometry import radius_profile
    c=Component(kind='nosecone',length=.3,radius=.05,
        metadata={'nose_shape':'ogive','shape_parameter':.5,'isflipped':True})
    xs=np.array([0,.15,.3])
    radii=radius_profile(c,xs)
    assert radii[0]==pytest.approx(.05)
    assert radii[-1]==pytest.approx(0,abs=1e-10)
    m=component_mesh(Project(),c)
    ring=m.vertices[np.isclose(m.vertices[:,0],.15)]
    assert np.linalg.norm(ring[:,1:],axis=1).max()==pytest.approx(radii[1])
