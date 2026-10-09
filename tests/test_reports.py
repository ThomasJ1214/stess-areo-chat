"""Offline report safety, provenance and actual-data plotting checks."""
from html.parser import HTMLParser
import math

from rocket_workbench.reports import MAX_PLOT_POINTS, render_report


class InspectReport(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.attributes = []
        self.plotted = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        attributes = dict(attrs)
        self.attributes.append(attributes)
        if tag == 'polyline':
            self.plotted.append([tuple(map(float, point.split(',')))
                                 for point in attributes['points'].split()])


def flight_result(trajectory):
    return {'summary': {'apogee_m': 98765, 'max_stress_pa': None},
            'trajectory': trajectory, 'events': [{'name': 'max_q', 'time': 25, 'index': 250}],
            'fidelity': 'Point-mass trajectory; quasi-static stress estimates',
            'backend': 'CPU', 'warnings': ['No attitude integration'],
            'validity': {'six_dof': False},
            'inputs': {'project_name': 'Test rocket', 'project_sha256': 'b' * 64,
                       'conditions': {'altitude': 900, 'wind_speed': 4}, 'options': {}}}


def test_report_escapes_user_text_and_has_no_active_or_external_resources():
    result = flight_result([])
    payload = '<script>alert("unsafe")</script><img src="https://example.com/track">'
    result['inputs']['project_name'] = payload
    result['warnings'] = [payload]
    result['fidelity'] = payload
    rendered = render_report('flight', result)
    parsed = InspectReport(rendered)
    assert 'script' not in parsed.tags
    assert 'img' not in parsed.tags
    assert 'iframe' not in parsed.tags
    assert 'link' not in parsed.tags
    assert '&lt;script&gt;' in rendered
    assert not any('src' in attrs or 'href' in attrs or any(key.startswith('on') for key in attrs)
                   for attrs in parsed.attributes)
    assert 'b' * 64 in rendered
    assert 'Six dof' in rendered and '>No<' in rendered
    assert 'No attitude integration' not in rendered  # payload replaced original warning


def test_long_flight_is_bounded_and_downsampling_retains_recorded_peak():
    rows = [{'time': i / 10, 'altitude': 98765 if i == 2537 else i % 100,
             'dynamic_pressure': 250000 if i == 1457 else i % 1000, 'stress': None,
             'structural_components': [{'secret': 'large-array-content-not-for-report'}]}
            for i in range(5000)]
    rendered = render_report('flight', flight_result(rows))
    plots = InspectReport(rendered).plotted
    assert len(plots) == 2
    assert all(len(points) <= MAX_PLOT_POINTS for points in plots)
    # The rare recorded extrema remain in their plot at its actual upper bound.
    assert min(y for _, y in plots[0]) == 18
    assert min(y for _, y in plots[1]) == 18
    assert '98765' in rendered and '250000' in rendered
    assert 'of 5000 finite recorded samples' in rendered
    assert 'large-array-content-not-for-report' not in rendered
    assert 'stress estimate: Unavailable' in rendered
    assert 'Estimated stress (Pa)' not in rendered
    assert len(rendered) < 40000


def test_missing_stress_values_are_gaps_and_real_zero_is_retained():
    rows = [{'time': i, 'altitude': i, 'dynamic_pressure': i,
             'stress': value} for i, value in enumerate([1, 0, None, 3, 4])]
    rendered = render_report('flight', flight_result(rows))
    plots = InspectReport(rendered).plotted
    assert len(plots) == 4  # altitude, pressure, then two separate stress segments
    assert [len(points) for points in plots[-2:]] == [2, 2]
    assert plots[-2][-1][1] == 216  # recorded zero lies on the actual lower bound
    assert 'Showing 4 of 4 finite recorded samples' in rendered


def test_cfd_report_preserves_nonconvergence_and_omits_field_arrays():
    result = {'fidelity': 'Experimental inviscid Euler CFD', 'backend': 'CPU NumPy',
              'warnings': ['Pressure drag has no viscous contribution'],
              'summary': {'converged': False, 'status': 'step_budget', 'residual': .02},
              'history': [{'step': 1, 'residual': 1, 'wall_pressure_residual': 2},
                          {'step': 2, 'residual': .02, 'wall_pressure_residual': .08}],
              'surface': [{'pressure_pa': 'surface-field-must-not-be-dumped'}] * 20000,
              'vertices': [['vertex-field-must-not-be-dumped']] * 20000}
    rendered = render_report('cfd', result)
    assert 'step_budget' in rendered and 'Converged' in rendered and '>No<' in rendered
    assert 'Experimental inviscid Euler CFD' in rendered
    assert 'Pressure drag has no viscous contribution' in rendered
    assert 'surface-field-must-not-be-dumped' not in rendered
    assert 'vertex-field-must-not-be-dumped' not in rendered
    assert len(InspectReport(rendered).plotted) == 2
    assert 'Run inputs were not recorded' in rendered


def test_comparison_report_labels_bases_and_reports_failed_flight():
    rendered = render_report('comparison', {
        'fidelity': 'Engineering comparison', 'warnings': [],
        'original': {'aero': {'mass_kg': 3, 'cp_m': 1.2, 'fidelity': 'Reference estimate'},
                     'flight_error': 'Missing motor <curve>'},
        'replacement': {'aero': {'mass_kg': 4, 'cp_m': 1.2, 'fidelity': 'Reference estimate'}},
        'deltas': {'mass_kg': 1}, 'configurations': [{'name': 'Unsupported', 'error': 'Unsupported stage'}]})
    assert 'Original OpenRocket geometry' in rendered
    assert 'Current replacement geometry' in rendered
    assert 'Current minus original differences' in rendered
    assert 'Flight unavailable: Missing motor &lt;curve&gt;' in rendered
    assert 'Unsupported stage' in rendered


def test_study_report_bounds_rows_and_preserves_failed_sample_exclusion():
    result = {'fidelity': 'Seeded engineering study', 'backend': 'CPU',
              'warnings': ['Statistics exclude failed samples'], 'parameter': 'wind_speed', 'seed': 9,
              'gust_seed_policy': 'independent per sample', 'statistics': {'apogee_m': {'mean': 1200, 'std': 50}},
              'rows': [{'index': i, 'value': i, 'apogee_m': 1200} for i in range(200)],
              'failures': [{'index': 201, 'value': -1, 'error': 'Invalid wind speed'}]}
    rendered = render_report('monte_carlo', result)
    assert 'Showing 80 of 200 rows' in rendered
    assert 'Excluded failed samples' in rendered and 'Invalid wind speed' in rendered
    assert 'Statistics exclude failed samples' in rendered
    assert 'independent per sample' in rendered
    assert len(rendered) < 30000


def test_comparison_preserves_each_solver_method_backend_and_limits():
    result = {'fidelity': 'Comparison aggregate', 'warnings': [],
              'original': {'aero': {'mass_kg': 3, 'fidelity': 'Original-reference estimate',
                                    'warnings': ['Small-angle only'], 'backend': 'CPU NumPy'},
                           'structure': {'fidelity': 'Beam/fin estimate', 'backend': 'CPU NumPy',
                                         'warnings': ['No joints'], 'components': [
                                             {'name': 'Unsupported CAD', 'material': 'Aluminum',
                                              'supported': False, 'stress_pa': 0, 'deflection_m': 0,
                                              'safety_factor': None, 'fidelity': 'unsupported',
                                              'warnings': ['Use solid FEA']}]}},
              'replacement': {'flight': {'summary': {'apogee_m': 42}, 'trajectory': [],
                                         'fidelity': 'Point-mass flight', 'backend': 'CPU',
                                         'warnings': ['No attitude integration']},
                              'cfd': {'summary': {'converged': False}, 'history': [],
                                      'fidelity': 'Experimental Euler', 'backend': 'cupy-cuda',
                                      'warnings': ['No viscous stresses']}}}
    rendered = render_report('comparison', result)
    for text in ('Original-reference estimate', 'Small-angle only', 'Beam/fin estimate',
                 'No joints', 'Use solid FEA', 'Point-mass flight', 'No attitude integration',
                 'Experimental Euler', 'cupy-cuda', 'No viscous stresses'):
        assert text in rendered
    # An unsupported row must not display the raw result's placeholder zeroes
    # as a stress/deflection or make an implied strength claim.
    unsupported_row = rendered.split('<td>Unsupported CAD</td>', 1)[1].split('</tr>', 1)[0]
    assert unsupported_row.count('<td>Unavailable</td>') == 3
    assert '<td>0</td>' not in unsupported_row


def test_fea_report_retains_physical_support_loads_and_omits_large_fields():
    result = {'fidelity': 'linear-static isotropic solid FEA', 'backend': 'CPU SciPy',
              'warnings': ['No composite laminate model'],
              'summary': {'boundary_condition': 'min-X fixed', 'load_mode': 'traction',
                          'traction_pa': [1234, 0, 0], 'max_displacement_m': .000123,
                          'max_von_mises_pa': 4567, 'relative_equilibrium_residual': 1e-12},
              'vertices': [['full-field-marker']] * 10000,
              'displacements': [['displacement-field-marker']] * 10000,
              'inputs': {'project_sha256': 'c' * 64, 'geometry_signature': 'd' * 64,
                         'conditions': {'speed': 100}, 'options': {'component_id': 'payload'}}}
    rendered = render_report('fea', result)
    for text in ('min-X fixed', 'traction', '1234', '0.000123', '4567', '1e-12',
                 'No composite laminate model', 'c' * 64, 'd' * 64, 'payload'):
        assert text in rendered
    assert 'full-field-marker' not in rendered
    assert 'displacement-field-marker' not in rendered
    assert len(rendered) < 10000


def test_all_cfd_convergence_gates_have_recorded_plots_and_finite_missing_gaps():
    rows = [{'step': i, 'residual': .1 / i, 'wall_pressure_residual': .2 / i,
             'force_residual': .3 / i, 'moment_residual': .4 / i} for i in range(1, 4)]
    rows[1]['force_residual'] = float('nan')
    rendered = render_report('cfd', {'history': rows, 'summary': {'converged': False}})
    parsed = InspectReport(rendered)
    assert 'Resultant-force steady residual' in rendered
    assert 'Centered-moment steady residual' in rendered
    assert all(math.isfinite(coordinate) for points in parsed.plotted for point in points for coordinate in point)
    assert all(math.isfinite(float(attrs[key])) for attrs in parsed.attributes
               for key in ('cx', 'cy') if key in attrs)
    assert len(parsed.plotted) == 3  # two separate force points are circles
    assert parsed.tags.count('circle') == 2


def test_reports_retain_flight_accuracy_and_actual_transient_scope_without_field_dump():
    flight = flight_result([])
    flight['numerical_integration'] = {'method': 'adaptive_rk4_step_doubling',
        'relative_tolerance': 1e-7, 'error_scope': 'Local error; not physical validation'}
    report = render_report('flight', flight)
    assert 'adaptive_rk4_step_doubling' in report and '1e-07' in report
    assert 'Local error; not physical validation' in report
    transient = {'summary': {'mode': 'transient', 'converged': False},
        'transient': {'duration_s': .02, 'completed': True,
            'scope': 'One-way prescribed launch airflow on fixed geometry',
            'temporal_sampling': 'Actual accepted states only',
            'frames': [{'time_s': .02, 'flight_time_s': 4.1,
                'freestream_mach': .8, 'pressure_drag_n': 123,
                'flow_velocity_m_s': ['large-transient-field'] * 10000}]}}
    report = render_report('cfd', transient)
    for text in ('Actual accepted states only', 'One-way prescribed launch airflow', '4.1', '123', 'not converged steady drag'):
        assert text in report
    assert 'large-transient-field' not in report and len(report) < 10000
