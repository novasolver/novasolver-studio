"""Structural body and face loads, shared by the preview and final engines. SI throughout."""
from __future__ import annotations

import numpy as np

from . import units
from .store import StudioError


def direction(value):
    if isinstance(value, str):
        v = np.zeros(3)
        v['xyz'.index(value[-1])] = -1 if value.startswith('-') else 1
    else:
        v = np.asarray(value, float)
    return v / np.linalg.norm(v)


def acceleration(case):
    p = case.get('physics', {})
    g, rot = p.get('gravity', {}), p.get('rotation', {})
    gravity = units.to_si(g.get('g', 9.81))*direction(g.get('direction', '-z')) if g.get('enabled') else np.zeros(3)
    axis = direction(rot.get('axis', 'z'))
    point = np.asarray(rot.get('axis_point', [0, 0, 0]), float)*1e-3
    omega2 = (float(rot.get('rpm', 0))*np.pi/30)**2 if rot.get('enabled') else 0.
    def at(x):
        r = x-point
        radial = r-(r@axis)[:, None]*axis
        return gravity[None, :] + omega2*radial
    return at if g.get('enabled') or rot.get('enabled') else None


def surface_rule(nodes, tri):
    """Curved tri6 quadrature: positions, area weights and shape functions."""
    q, w = np.polynomial.legendre.leggauss(6)
    q, w = (q+1)/2, w/2
    X = nodes[tri]
    points, weights, shapes = [], [], []
    for i, a in enumerate(q):
        for j, b in enumerate(q):
            L = np.array([1-a-(1-a)*b, a, (1-a)*b])
            N = np.r_[L*(2*L-1), 4*L[0]*L[1], 4*L[1]*L[2], 4*L[2]*L[0]]
            dL = np.array([[-1, 1, 0], [-1, 0, 1]])
            dN = np.column_stack([dL*(4*L-1),
                4*(dL[:, 0]*L[1]+L[0]*dL[:, 1]),
                4*(dL[:, 1]*L[2]+L[1]*dL[:, 2]),
                4*(dL[:, 2]*L[0]+L[2]*dL[:, 0])])
            J = np.einsum('ik,ekj->eij', dN, X)
            points.append(np.einsum('i,eij->ej', N, X))
            weights.append(w[i]*w[j]*(1-a)*np.linalg.norm(np.cross(J[:, 0], J[:, 1]), axis=1))
            shapes.append(N)
    return np.stack(points, 1), np.stack(weights, 1), np.asarray(shapes)


def face_load(case, face, nodes, tri, b):
    if b['role'] == 'bearing':
        desc = next((f for f in case['geometry'].get('faces', []) if f['key'] == face), {})
        if desc.get('type') != 'Cylinder' or not all(k in desc for k in ('axis', 'axis_point', 'radius')):
            raise StudioError('err.bearing_axis', 400, face=face)
    p, w, N = surface_rule(nodes, tri)
    area = w.sum()
    center = np.einsum('eq,eqi->i', w, p)/area
    r = p-center
    role = b['role']
    force = np.zeros(3)
    torque = np.zeros(3)
    traction = np.zeros_like(p)
    if role == 'moment':
        torque = units.to_si(b['torque'])*direction(b.get('direction', '+z'))
    elif role == 'remote-force':
        force = units.to_si(b['force'])*direction(b.get('direction', '-z'))
        point = np.asarray(units.to_si(b['point']))
        torque = np.cross(point-center, force)
        traction += force/area
    elif role == 'bearing':
        axis = direction(desc['axis'])
        force = units.to_si(b['force'])*direction(b.get('direction', '+x'))
        if abs(force@axis) > max(np.linalg.norm(force), 1.)*1e-10:
            raise StudioError('err.bearing_direction', 400, face=face)
        radial = p-np.asarray(desc['axis_point'])
        radial -= (radial@axis)[..., None]*axis
        radial /= np.linalg.norm(radial, axis=2)[..., None]
        d = direction(b.get('direction', '+x'))
        cosine = np.maximum(radial@d, 0)
        # Solve for the tiny transverse quadrature correction within the loaded half. All tractions stay radial.
        loaded = cosine > 0
        H = np.einsum('eq,eqi,eqj->ij', w*loaded, radial, radial)
        coefficient = np.linalg.pinv(H, rcond=1e-12)@force
        traction = loaded[..., None]*(radial@coefficient)[..., None]*radial
    if np.any(torque):
        inertia = np.eye(3)*np.sum(w*np.sum(r*r, axis=2))-np.einsum('eq,eqi,eqj->ij', w, r, r)
        spin = np.linalg.solve(inertia, torque)
        traction += np.cross(spin, r)
    nodal = np.einsum('eq,qi,eqj->eij', w, N, traction)
    return nodal


def temperatures(case, mesh, progress):
    p = case.get('physics', {})
    load = p.get('thermal_load', {})
    if isinstance(load, str):
        load = {'mode': load}
    mode = load.get('mode', 'none')
    if mode == 'uniform':
        return np.full(len(mesh['nodes']), units.to_si(load.get('temperature', {'value': 120, 'unit': 'degC'})))
    if mode == 'solve':
        from .fem_tet10 import solve_thermal
        from .run_worker import thermal_groups
        from .templates import element_prop
        fixed, flux, conv, _ = thermal_groups(case, mesh, nested=True)
        if not fixed and not conv:
            raise StudioError('err.no_temperature', 400)
        return solve_thermal(mesh['nodes'], mesh['tets'], element_prop(case, mesh, 'k'), fixed, flux, conv,
                             progress=progress)['T']
    return None


def comparison(case, quantity, computed, expected, unit, formula, **extra):
    error = (computed/expected-1)*100 if expected else abs(computed)
    tol = case['reference'].get('tolerance_pct', 2.)
    return {'applicable': True, 'quantity': quantity, 'computed': float(computed), 'reference': float(expected),
            'unit': unit, 'formula': formula, 'error_pct': float(error), 'tolerance_pct': tol,
            'pass': bool(abs(error) <= tol), **extra}


def modal_reference(case, table):
    from .reference_loads import unsupported_loads
    excluded = unsupported_loads(case)
    if excluded:
        return excluded
    b = case['boundaries']
    na = {'applicable': False, 'why_key': 'verify.structural_pattern_reason'}
    if case['template'] != 'cantilever-modal' or case.get('body_materials') or b['x0']['role'] != 'fixed' or any(
            v['role'] not in ('free', 'load', 'pressure', 'moment', 'bearing', 'remote-force') for f,v in b.items() if f != 'x0'):
        return na
    from .templates import solid_props
    mat = solid_props(case)
    p = case['geometry']['params']
    L, w, h = (units.to_si(p[k]) for k in ('length','width','height'))
    scale = np.sqrt(mat['E']*min(w,h)**2/(12*mat['rho']*L**4))/(2*np.pi)
    ref = comparison(case, 'frequency', table[0]['frequency_hz'], 1.8751040687**2*scale, 'Hz',
                     'Euler–Bernoulli beam: f = beta^2/(2 pi) sqrt(EI/(rho A L^4))')
    if len(table) >= 3 and abs(w/h-1) < 1e-8:
        second = comparison(case, 'frequency', table[2]['frequency_hz'], 4.694091133**2*scale, 'Hz', ref['formula'])
        ref['second_bending'] = second
        ref['pass'] = ref['pass'] and second['pass']
    return ref


def reference(case, mesh, r, metrics):
    from .templates import solid_props
    from .reference_loads import unsupported_loads
    tid = case['template']
    expected = {'thermal-bar-fixed': {'thermal'}, 'thermal-bar-free': {'thermal'}, 'hanging-bar': {'gravity'},
                'rotating-disk': {'rotation'}}
    excluded = unsupported_loads(case, expected.get(tid, ()))
    if excluded:
        return excluded
    na = {'applicable': False, 'why_key': 'verify.structural_pattern_reason'}
    if case.get('body_materials'):
        return na
    tid, b, p = case['template'], case['boundaries'], case['geometry'].get('params', {})
    mat = solid_props(case)
    E, nu, rho, alpha = (mat[k] for k in ('E','nu','rho','alpha'))
    x, u, stress = mesh['nodes'], r['u'], r['s']
    if tid.startswith('thermal-bar-'):
        fixed = tid.endswith('fixed')
        expected_roles = {'x0': 'constraint', 'x1': 'constraint' if fixed else 'free', 'y0': 'symmetry',
                          'y1': 'free', 'z0': 'symmetry', 'z1': 'free'}
        load = case['physics'].get('thermal_load', {})
        if any(b[f]['role'] != v for f,v in expected_roles.items()) or b['x0'].get('components') != 'x' or (
                fixed and b['x1'].get('components') != 'x') or load.get('mode') != 'uniform' or alpha <= 0:
            return na
        dt = units.to_si(load.get('temperature', {'value': 120,'unit':'degC'}))-units.to_si(case['physics'].get('T_ref', {'value':20,'unit':'degC'}))
        L = units.to_si(p['length'])
        if dt == 0:
            return na
        middle = (x[:,0] > L/3)&(x[:,0] < 2*L/3)
        metrics['thermal_stress_pa'] = float(np.abs(stress[middle,0]).mean())
        metrics['elongation_m'] = float(u[np.unique(mesh['face_x1']),0].mean())
        if fixed:
            return comparison(case,'thermal_stress', metrics['thermal_stress_pa'], abs(E*alpha*dt),'Pa','sigma_x = -E alpha deltaT')
        ref = comparison(case,'elongation', metrics['elongation_m'],alpha*dt*L,'m','delta = alpha deltaT L')
        ref['max_stress_pa'] = float(np.abs(stress).max())
        ref['stress_limit_pa'] = abs(E*alpha*dt)*.01
        ref['pass'] &= ref['max_stress_pa'] < ref['stress_limit_pa']
        return ref
    if tid == 'hanging-bar':
        g = case['physics'].get('gravity',{})
        roles = {'x0':'symmetry','y0':'symmetry','z1':'constraint','x1':'free','y1':'free','z0':'free'}
        if not g.get('enabled') or g.get('direction') != '-z' or b['z1'].get('components') != 'z' or any(b[f]['role'] != v for f,v in roles.items()):
            return na
        L = units.to_si(p['height']); gravity = units.to_si(g.get('g',9.81))
        metrics['top_stress_pa'] = float(stress[np.unique(mesh['face_z1']),2].mean())
        metrics['tip_disp_m'] = float(-u[np.unique(mesh['face_z0']),2].mean())
        ref = comparison(case,'tip_disp',metrics['tip_disp_m'],rho*gravity*L**2/(2*E),'m','delta = rho g L^2/(2 E)')
        ref['stress'] = comparison(case,'top_stress',metrics['top_stress_pa'],rho*gravity*L,'Pa','sigma = rho g L')
        ref['pass'] &= ref['stress']['pass']
        return ref
    if tid == 'rotating-disk':
        rot = case['physics'].get('rotation',{})
        if not rot.get('enabled') or rot.get('axis') != 'z' or rot.get('axis_point') != [0,0,0] or any(
                b[f]['role'] != ('symmetry' if f in ('x0','y0','z0') else 'free') for f in b):
            return na
        R = units.to_si(p['radius']); omega = float(rot['rpm'])*np.pi/30
        center = np.hypot(x[:,0],x[:,1]) < R*1e-7
        metrics['center_stress_pa'] = float(stress[center,:2].mean())
        return comparison(case,'center_stress',metrics['center_stress_pa'],(3+nu)/8*rho*omega**2*R**2,'Pa',
                          'sigma_r(0) = sigma_theta(0) = (3+nu) rho omega^2 R^2/8 (plane stress)')
    if tid == 'shaft-torsion':
        if b['z0']['role'] != 'fixed' or b['z1']['role'] != 'moment' or b['z1'].get('direction') != '+z' or b['outer']['role'] != 'free':
            return na
        R,L = (units.to_si(p[k]) for k in ('radius','height'))
        torque = units.to_si(b['z1']['torque']); G = E/(2*(1+nu)); J = np.pi*R**4/2
        end = np.unique(mesh['face_z1']); radial2 = (x[end,:2]**2).sum(1)
        metrics['twist_rad'] = float(np.sum(x[end,0]*u[end,1]-x[end,1]*u[end,0])/radial2.sum())
        radius = np.hypot(x[:,0],x[:,1])
        middle = (x[:,2] > L/3)&(x[:,2] < 2*L/3)&(radius > R*.999)
        metrics['shear_pa'] = float((r['vm'][middle]/np.sqrt(3)).mean())
        ref = comparison(case,'twist',metrics['twist_rad'],torque*L/(G*J),'rad','phi = T L/(G J)')
        ref['shear'] = comparison(case,'shear',metrics['shear_pa'],abs(torque)*R/J,'Pa','tau = T R/J')
        ref['pass'] &= ref['shear']['pass']
        return ref
    return na
