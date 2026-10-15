"""Run independent plate-draft references; this is not an application solver.

Run from the repository: .venv/bin/python research/validate_plate_draft.py
Results go to ignored build/research-plate-reference.json. Requires the existing
NumPy/SciPy environment, but no GUI, mesher or external solver.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DRAFT = ROOT / "research/prototypes/plate_fea.py.txt"


def load_draft():
    # Deliberate execution of this repository's trusted, unmodified text draft.
    # It remains outside the installed/importable solver package.
    namespace = {"__name__": "rocket_workbench.solvers.research_plate_draft",
                 "__package__": "rocket_workbench.solvers"}
    exec(compile(DRAFT.read_text(), str(DRAFT), "exec"), namespace)
    return namespace


def navier_center(young, poisson, thickness, pressure, terms=101):
    """Independent Fourier-series solution: hard simply supported unit square.

    D = E h^3/[12(1-nu^2)], S = (5/6) G h.
    Each odd (m,n) load term contributes q_mn/(D k^4) + q_mn/(S k^2).
    w=0 and tangential rotation=0 on the boundary. This is not the soft support
    with only w constrained. Terms at the center have alternating signs.
    """
    bending = young*thickness**3/(12*(1-poisson**2))
    shear = (5/6)*young/(2*(1+poisson))*thickness
    value = 0.
    for m in range(1, terms+1, 2):
        for n in range(1, terms+1, 2):
            load = 16*pressure/(np.pi**2*m*n)
            k2 = np.pi**2*(m*m+n*n)
            sign = (-1)**((m-1)//2+(n-1)//2)
            value += sign*load*(1/(bending*k2*k2)+1/(shear*k2))
    return float(value)


def main():
    draft = load_draft()
    E, nu, pressure = 70e9, .3, 1000.
    vertices = np.array([[0., 0.], [1., 0.], [1., 1.], [0., 1.]])
    model = draft['mitc4_matrices'](vertices, E, nu, .01)
    K = model['stiffness']
    # A rigid transverse translation and two rigid tilts must have zero energy.
    rigid = []
    for offset, slope_x, slope_y in [(1., 0., 0.), (0., 1., 0.), (0., 0., 1.)]:
        state = np.column_stack((offset+slope_x*vertices[:, 0]+slope_y*vertices[:, 1],
                                 np.full(4, slope_x), np.full(4, slope_y))).ravel()
        residual = float(np.linalg.norm(K@state)/(np.linalg.norm(K)*np.linalg.norm(state)))
        assert residual < 1e-13, residual
        rigid.append(residual)
    # Constant cylindrical curvature is shear free at the MITC tying points.
    curvature = .2
    state = np.column_stack((.5*curvature*vertices[:, 0]**2,
                             curvature*vertices[:, 0], np.zeros(4))).ravel()
    expected = .5*(E*.01**3/(12*(1-nu**2)))*curvature**2
    energy = float(.5*state@K@state)
    assert abs(energy/expected-1) < 1e-10
    eigenvalues = np.linalg.eigvalsh(K)
    assert np.count_nonzero(eigenvalues > np.linalg.norm(K)*1e-11) == 9
    rows = []
    for thickness in [.1, .01, .001]:
        # Scale loading with h^3 to keep every case in small deflection.
        case_pressure = pressure*(thickness/.1)**3
        reference = navier_center(E, nu, thickness, case_pressure)
        refined_reference = navier_center(E, nu, thickness, case_pressure, terms=201)
        assert abs(reference/refined_reference-1) < 1e-6
        errors = []
        for size in [.25, .125, .0625, .03125]:
            xy, elements = draft['polygon_quad_mesh'](vertices, size)
            x_edge = np.isclose(xy[:, 0], 0) | np.isclose(xy[:, 0], 1)
            y_edge = np.isclose(xy[:, 1], 0) | np.isclose(xy[:, 1], 1)
            fixed = np.unique(np.concatenate((3*np.flatnonzero(x_edge | y_edge),
                3*np.flatnonzero(x_edge)+2, 3*np.flatnonzero(y_edge)+1))).astype(int)
            result = draft['solve_plate'](xy, elements, E, nu, thickness, case_pressure, fixed)
            center = np.argmin(np.linalg.norm(xy-[.5, .5], axis=1))
            assert np.linalg.norm(xy[center]-[.5, .5]) < 1e-12
            displacement = float(result['dofs'][center, 0])
            error = abs(displacement/reference-1)
            assert result['force_balance_relative_error'] < 1e-6
            assert result['moment_balance_relative_error'] < 1e-6
            assert abs(result['external_work_j']/(2*result['strain_energy_j'])-1) < 1e-7
            errors.append(error)
            row = dict(thickness_m=thickness, pressure_pa=case_pressure, requested_mesh_m=size, elements=len(elements),
                center_displacement_m=displacement, navier_reference_m=reference,
                relative_error=error, force_balance_error=result['force_balance_relative_error'],
                moment_balance_error=result['moment_balance_relative_error'],
                free_dof_residual=result['relative_equilibrium_residual'])
            rows.append(row)
            print(json.dumps(row), flush=True)
        assert all(b < a for a, b in zip(errors, errors[1:])), errors
        assert errors[-1] < .001, errors
    receipt = dict(status='passed', scope='Draft element/rectangular plate references only; no app/CAD/fin integration',
        draft_sha256=hashlib.sha256(DRAFT.read_bytes()).hexdigest(),
        rigid_mode_relative_residuals=rigid, constant_curvature_energy_j=energy,
        constant_curvature_reference_energy_j=expected, cases=rows,
        unverified=['Distorted/skew/triangular fin meshes', 'Actual component placement/load mapping',
                    'CAD midsurfaces', 'Boundary/support choice', 'Stress convergence',
                    'UI and installed executable integration'])
    destination = ROOT/'build/research-plate-reference.json'
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(receipt, indent=2)+'\n')
    print(f'References passed; evidence: {destination}', flush=True)


if __name__ == '__main__':
    main()
