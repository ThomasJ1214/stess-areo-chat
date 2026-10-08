import gzip
import io
from pathlib import Path
import zipfile

import pytest

from rocket_workbench.imports import import_motor, import_ork


RSE = b'''<engine-database><engine-list><engine mfg="Test" code="H100" dia="38" len="200" initWt="400" propWt="200"><data>
<eng-data t="0" f="0"/><eng-data t="0.1" f="100"/><eng-data t="2" f="100"/><eng-data t="2.1" f="0"/>
</data></engine></engine-list></engine-database>'''

ORK = b'''<openrocket version="1.10"><rocket><name>Test dual rocket</name><id>rocket</id>
<motorconfiguration configid="h" default="true"><name>H flight</name><stage number="0" active="true"/></motorconfiguration>
<motorconfiguration configid="empty"><name>Dry</name><stage number="0" active="false"/></motorconfiguration>
<subcomponents><stage><id>stage</id><name>Main stage</name><subcomponents>
<nosecone><id>nose</id><length>0.3</length><aftradius>0.05</aftradius><thickness>0.002</thickness><shape>ogive</shape><shapeparameter>1</shapeparameter><material type="bulk" density="1850">Fiberglass</material></nosecone>
<bodytube><id>body</id><name>Body</name><length>1</length><radius>0.05</radius><thickness>0.002</thickness><material type="bulk" density="1850">Fiberglass</material><subcomponents>
<innertube><id>mount</id><length>0.25</length><outerradius>0.02</outerradius><thickness>0.001</thickness><position type="bottom">0</position><motormount><overhang>0.01</overhang><ignitionevent>launch</ignitionevent><motor configid="h"><designation>H100</designation><diameter>0.038</diameter><length>0.2</length></motor></motormount></innertube>
<trapezoidfinset><id>fin</id><rootchord>0.25</rootchord><tipchord>0.1</tipchord><height>0.12</height><sweeplength>0.1</sweeplength><fincount>4</fincount><thickness>0.004</thickness><axialoffset method="bottom">-0.02</axialoffset></trapezoidfinset>
<masscomponent><id>payload</id><packedlength>0.1</packedlength><packedradius>0.04</packedradius><mass>0.5</mass><axialoffset method="middle">0.02</axialoffset><overridecg>0.03</overridecg></masscomponent>
<parachute><id>drogue</id><packedlength>0.1</packedlength><packedradius>0.02</packedradius><diameter>0.3</diameter><cd>0.7</cd><deployevent>apogee</deployevent><deploydelay>0.4</deploydelay><material type="surface" density="0.05">Nylon</material></parachute>
<parachute><id>main</id><packedlength>0.1</packedlength><packedradius>0.02</packedradius><diameter>1.1</diameter><cd>1.5</cd><deployevent>altitude</deployevent><deployaltitude>180</deployaltitude><material type="surface" density="0.05">Nylon</material></parachute>
</subcomponents></bodytube></subcomponents></stage></subcomponents></rocket></openrocket>'''


def zipped(xml=ORK, motor=True, member="rocket.ork"):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(member, xml)
        if motor:
            z.writestr("thrustcurves/h100.rse", RSE)
    return out.getvalue()


def test_hierarchy_positions_configs_and_embedded_thrust():
    p = import_ork(zipped(), "test.ork")
    c = {c.id: c for c in p.components}
    assert p.name == "Test dual rocket"
    assert c["stage"].length == pytest.approx(1.3)
    assert c["nose"].x == 0
    assert c["body"].x == pytest.approx(0.3)
    assert c["mount"].parent_id == "body"
    assert c["mount"].x == pytest.approx(1.05)
    assert c["fin"].x == pytest.approx(1.03)
    assert c["payload"].x == pytest.approx(0.77)
    assert c["payload"].cg_override == pytest.approx(0.80)
    assert c["fin"].radius == pytest.approx(.05)
    cfg = p.configurations[0]
    assert cfg.motor_id == p.motors[0].id
    assert cfg.motor_mount_id == "mount"
    assert cfg.motor_position == pytest.approx(1.21)
    assert cfg.deployment == "dual"
    assert cfg.main_deploy_altitude == 180
    assert cfg.main_cd_area == pytest.approx(1.5 * 3.141592653589793 * (.55 ** 2))
    assert cfg.apogee_delay == .4
    assert "stage" not in p.configurations[1].active_component_ids
    assert "body" not in p.configurations[1].active_component_ids
    assert p.active_configuration_id == "h"
    assert c["main"].mass_override > 0
    assert any("no verified elastic" in w for w in p.import_warnings)


@pytest.mark.parametrize("data", [ORK, gzip.compress(ORK), zipped(motor=False)])
def test_plain_gzip_and_zip_preserve_unresolved_assignment(data):
    p = import_ork(data, "rocket.ork")
    assert p.configurations[0].motor_id is None
    assert p.metadata["motor_assignments"][0]["designation"] == "H100"
    assert any("matching .eng/.rse" in w for w in p.import_warnings)


def test_real_upstream_openrocket_dual_fixture():
    fixture = Path(__file__).parent / "fixtures/openrocket/dual-deployment.ork"
    p = import_ork(fixture.read_bytes(), fixture.name)
    assert p.name == "Dual parachute deployment"
    assert len(p.components) == 20
    assert len(p.configurations) == 6
    assert p.active_configuration_id == "098d8c95-54c4-4552-bf81-e65e1de4796b"
    assert all(c.deployment == "dual" for c in p.configurations)
    assert all(c.main_deploy_altitude == 152.4 for c in p.configurations)
    assert p.metadata["motor_assignments"][3]["designation"] == "H999N"
    assert len(p.motors) == 0  # This ORK references OpenRocket's external database.
    stage = next(c for c in p.components if c.kind == "stage")
    assert stage.mass_override == pytest.approx(1.3607771088)
    assert stage.metadata["mass_subcomponents_overridden"] is True
    assert stage.length == pytest.approx(1.47701)
    bulkhead = next(c for c in p.components if c.kind == "bulkhead")
    assert bulkhead.radius == pytest.approx(.027305 - .001905)


def test_unsupported_cluster_is_explicit():
    p = import_ork(ORK.replace(b"<length>0.25</length>", b"<length>0.25</length><clusterconfiguration>three</clusterconfiguration>"))
    assert "cluster" in p.metadata["unsupported_features"]
    assert any("clustered" in w for w in p.import_warnings)


def test_unknown_component_is_preserved_excluded_and_warned():
    p = import_ork(ORK.replace(b"<masscomponent>", b"<unknownwidget>").replace(b"</masscomponent>", b"</unknownwidget>"))
    c = next(c for c in p.components if c.id == "payload")
    assert not c.enabled
    assert c.metadata["unsupported"]
    assert any("Unsupported component" in w for w in p.import_warnings)


@pytest.mark.parametrize("data", [b'<openrocket><rocket>',
    b'<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]><openrocket><rocket><name>&x;</name></rocket></openrocket>',
    zipped(member="../rocket.ork"),
    ORK.replace(b"<radius>0.05</radius>", b"<radius>nan</radius>"),
    ORK.replace(b"<id>payload</id>", b"<id>body</id>")])
def test_invalid_or_unsafe_ork_rejected(data):
    with pytest.raises(ValueError):
        import_ork(data)


def test_rasp_units_multiple_motors_and_comments():
    data = b'; source comment\nH100 38 200 10-14-P .2 .4 Test\n0 0\n0.1 100\n2.1 0\n\n; next\nG80 29 150 P .1 .2 Test\n0 0\n.1 80\n1 0\n'
    motors = import_motor(data, "curves.eng")
    assert len(motors) == 2
    assert motors[0].diameter == .038
    assert motors[0].propellant_mass == .2
    assert motors[0].dry_mass == .2
    assert motors[1].length == .15


def test_rse_uses_grams_and_mm():
    m = import_motor(RSE, "h.rse")[0]
    assert m.diameter == .038
    assert m.dry_mass == .2
    assert m.curve[2] == [2, 100]


@pytest.mark.parametrize("data,filename", [(b'H 38 200 P .5 .2 M\n0 0\n1 100\n', 'x.eng'),
    (b'H 38 200 P .1 .2 M\n0 0\n0 100\n','x.eng'),
    (RSE.replace(b'f="100"', b'f="-100"'),'x.rse'),
    (RSE.replace(b't="2"', b't="0.1"'),'x.rse'),
    (b'garbage','x.eng')])
def test_bad_motor_curves_rejected(data, filename):
    with pytest.raises(ValueError):
        import_motor(data, filename)


def test_motor_ejection_recovery_uses_real_motor_delay_and_device_delay():
    xml=ORK.replace(b'<deployevent>apogee</deployevent>',b'<deployevent>ejection</deployevent>')
    xml=xml.replace(b'<designation>H100</designation>',b'<designation>H100</designation><delay>5</delay>')
    p=import_ork(zipped(xml))
    cfg=p.configurations[0]
    assert cfg.primary_deploy_event=='motor_ejection'
    assert cfg.motor_ejection_delay==5
    assert cfg.apogee_delay==.4
    assert cfg.deployment=='dual'
    assert 'deployment_event' not in p.metadata['unsupported_features']


def test_unknown_ejection_delay_is_preserved_and_warned_not_invented():
    xml=ORK.replace(b'<deployevent>apogee</deployevent>',b'<deployevent>ejection</deployevent>')
    p=import_ork(xml)
    cfg=p.configurations[0]
    assert cfg.primary_deploy_event=='motor_ejection'
    assert cfg.motor_ejection_delay is None
    assert any('no known ejection delay' in warning for warning in p.import_warnings)


def test_source_zero_thickness_is_preserved_without_invented_mass():
    p=import_ork(ORK.replace(b'<thickness>0.002</thickness>',b'<thickness>0</thickness>'))
    c=next(c for c in p.components if c.id=='body')
    assert c.thickness==0
    assert c.mass_override==0
    assert c.metadata['zero_thickness']
    assert any('zero wall thickness' in w for w in p.import_warnings)


def test_legacy_virtual_stock_texture_paths_are_ignored_safely():
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('rocket.ork',ORK)
        z.writestr('/datafiles/textures/balsa.jpg',b'ignored untrusted texture')
    assert import_ork(out.getvalue()).name=='Test dual rocket'


def test_unrelated_inactive_stage_does_not_block_single_stage_configuration():
    extra = b'''<stage><id>booster-stage</id><subcomponents><bodytube><id>booster-body</id>
    <length>0.4</length><radius>0.05</radius><subcomponents><innertube><id>cluster-mount</id>
    <length>0.2</length><clusterconfiguration>three</clusterconfiguration>
    </innertube></subcomponents></bodytube></subcomponents></stage>'''
    xml = ORK.replace(b'<stage number="0" active="true"/>',
                      b'<stage number="0" active="true"/><stage number="1" active="false"/>')
    xml = xml.replace(b'</stage></subcomponents></rocket>',
                      b'</stage>' + extra + b'</subcomponents></rocket>')
    project = import_ork(xml)
    scopes = project.metadata['unsupported_features_by_configuration']
    assert 'multistage' in project.metadata['unsupported_features']
    assert 'cluster' in project.metadata['unsupported_features']
    assert scopes['h'] == []
    assert scopes['empty'] == ['cluster']
    assert 'booster-body' not in project.configurations[0].active_component_ids
    assert 'cluster-mount' in project.configurations[1].active_component_ids


def test_missing_or_zero_area_recovery_does_not_invent_a_flight_parachute():
    import re
    no_recovery = re.sub(rb'<parachute>.*?</parachute>', b'', ORK, flags=re.DOTALL)
    project = import_ork(no_recovery)
    assert not project.configurations[0].recovery_defined
    assert project.metadata['recovery_assignments']['h'] == []
    assert any('Flight is blocked' in warning for warning in project.import_warnings)
    zero_area = import_ork(ORK.replace(b'<diameter>0.3</diameter>', b'<diameter>0</diameter>'))
    assert not zero_area.configurations[0].recovery_defined
    assert any('zero Cd' in warning for warning in zero_area.import_warnings)


@pytest.mark.parametrize('before,after', [
    (b'<length>0.25</length>', b'<length>0.25</length><instancecount>1.5</instancecount>'),
    (b'<diameter>0.3</diameter>', b'<diameter>-0.3</diameter>'),
    (b'<deploydelay>0.4</deploydelay>', b'<deploydelay>-0.4</deploydelay>'),
])
def test_invalid_physical_import_values_are_not_silently_rounded_or_clamped(before, after):
    with pytest.raises(ValueError):
        import_ork(ORK.replace(before, after))
