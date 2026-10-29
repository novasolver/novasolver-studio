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
        T = np.full(len(mesh['nodes']), units.to_si(load.get('temperature', {'value': 120, 'unit': 'degC'})))
        for body,q in load.get('body_temperatures',{}).items():
            idx = np.unique(mesh['tets'][mesh['tet_body'] == int(body[1:])])
            T[idx] = units.to_si(q)
        return T
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


def rubber_uniaxial(E,nu,stretch):
    """Exact homogeneous, zero lateral Cauchy stress for the log-J compressible neo-Hookean law."""
    from scipy.optimize import brentq
    mu,lam = E/(2*(1+nu)),E*nu/((1+nu)*(1-2*nu))
    lateral = brentq(lambda a: mu*(a*a-1)+lam*np.log(stretch*a*a),.001,10.)
    J = stretch*lateral*lateral
    return {'lateral_stretch':lateral,'cauchy_pa':mu*(stretch*stretch-lateral*lateral)/J,
            'nominal_pa':mu*(stretch*stretch-lateral*lateral)/stretch}


def follower_pressure(case,mesh):
    """Dead direction for all other loads; pressure follows the current tri6 area vector.
    Differentiate that area vector, including its area change, for the Newton tangent.
    """
    import scipy.sparse as sp
    from .fem_tet10 import outward_normals,canonical_tets
    faces = [(mesh['face_'+f],units.to_si(b['pressure'])) for f,b in case['boundaries'].items() if b['role'] == 'pressure']
    if not faces:
        return None
    nodes = mesh['nodes']; ndof = 3*len(nodes)
    tets = canonical_tets(nodes,mesh['tets'])
    rules = []
    q,w = np.polynomial.legendre.leggauss(3); q,w = (q+1)/2,w/2
    for tri,p in faces:
        norm = outward_normals(nodes,tets,tri)
        cross = np.cross(nodes[tri[:,1]]-nodes[tri[:,0]],nodes[tri[:,2]]-nodes[tri[:,0]])
        sign = np.sign(np.einsum('ei,ei->e',cross,norm))
        dofs = (3*tri[:,:,None]+np.arange(3)).reshape(-1,18)
        for i,a in enumerate(q):
            for j,b in enumerate(q):
                L = np.array([(1-a)*(1-b),a,(1-a)*b]); dL = np.array([[-1,1,0],[-1,0,1]])
                N = np.r_[L*(2*L-1),4*L[0]*L[1],4*L[1]*L[2],4*L[2]*L[0]]
                dN = np.column_stack([dL*(4*L-1),*[4*(dL[:,k]*L[l]+L[k]*dL[:,l]) for k,l in ((0,1),(1,2),(2,0))]])
                rules.append((tri,dofs,N,dN,-p*sign*w[i]*w[j]*(1-a)))
    def evaluate(U):
        force = np.zeros(ndof); K = sp.csr_matrix((ndof,ndof)); x = nodes+U
        for tri,dofs,N,dN,weight in rules:
            jac = np.einsum('ka,eai->eki',dN,x[tri])
            load = weight[:,None,None]*N[None,:,None]*np.cross(jac[:,0],jac[:,1])[:,None,:]
            np.add.at(force,dofs.ravel(),load.ravel())
            deriv = np.empty((len(tri),6,3,6,3))
            for c in range(3):
                v = np.eye(3)[c]
                da = (dN[0][None,:,None]*np.cross(v,jac[:,1])[:,None,:]+
                      dN[1][None,:,None]*np.cross(jac[:,0],v)[:,None,:])
                deriv[:,:,:,:,c] = weight[:,None,None,None]*N[None,:,None,None]*da.transpose(0,2,1)[:,None,:,:]
            K += sp.csr_matrix((deriv.reshape(-1,18,18).ravel(),(np.repeat(dofs,18,axis=1).ravel(),np.tile(dofs,(1,18)).ravel())),shape=(ndof,ndof))
        return force,K
    return evaluate


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
    if tid in ('press-fit','stacked-blocks','friction-block','large-cantilever','plastic-bar','plastic-beam-collapse','rubber-tension'):
        return nonlinear_reference(case,mesh,r,metrics)
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


def nonlinear_reference(case,mesh,r,metrics):
    from .templates import solid_props
    from .reference_loads import unsupported_loads
    excluded = unsupported_loads(case)
    if excluded:
        return excluded
    tid = case['template']; p = case['geometry']['params']; props = solid_props(case)
    E,nu = props['E'],props['nu']
    na = {'applicable':False,'why_key':'verify.structural_pattern_reason'}
    if tid in ('press-fit','stacked-blocks','friction-block'):
        contact = r.get('interfaces',{}).get('interface')
        if not contact:
            return na
        if tid == 'press-fit':
            from .contact import settings
            if settings(case,'interface')['type'] != 'frictionless' or any(
                    abs(solid_props(case,b)[k]/props[k]-1)>1e-10 for b in case.get('body_materials',{}) for k in ('E','nu')):
                return na
            b,c = (units.to_si(p[k]) for k in ('radius','outer_radius'))
            offset = units.to_si(case.get('contacts',{}).get('interface',{}).get('offset',0))
            if offset <= 0:
                return na
            pressure = E*offset/b*(c*c-b*b)/(2*c*c)
            metrics['contact_pressure_pa'] = contact['pressure_pa']
            x = mesh['nodes']; radius = np.hypot(x[:,0],x[:,1]); ring = np.unique(mesh['tets'][mesh['tet_body'] == 2])
            nds = ring[np.abs(radius[ring]-b)<b*.01]
            theta = np.arctan2(x[nds,1],x[nds,0]); stress = r['s'][nds]
            hoop = stress[:,0]*np.sin(theta)**2+stress[:,1]*np.cos(theta)**2-2*stress[:,3]*np.sin(theta)*np.cos(theta)
            metrics['hoop_stress_pa'] = float(hoop.mean())
            ref = comparison(case,'contact_pressure',contact['pressure_pa'],pressure,'Pa','Lamé thick cylinders, plane stress: p = E delta/b (c²-b²)/(2c²)')
            ref['hoop'] = comparison(case,'hoop_stress',metrics['hoop_stress_pa'],pressure*(c*c+b*b)/(c*c-b*b),'Pa','Lamé ring bore: sigma_theta = p (c²+b²)/(c²-b²)')
            ref['pass'] &= ref['hoop']['pass']
            return ref
        pressure = units.to_si(case['boundaries']['top'].get('pressure',0))
        area = units.to_si(p['length'])*units.to_si(p['width'])
        if pressure<=0:
            return na
        if tid == 'stacked-blocks':
            metrics['contact_force_n'] = contact['normal_force_n']
            ref = comparison(case,'contact_force',contact['normal_force_n'],pressure*area,'N','Uniform compression, sigma_z = -p; F = p A')
            ref['stress'] = comparison(case,'axial_stress',float(-r['s'][:,2].mean()),pressure,'Pa','Uniform compression: sigma_z = -p')
            ref['pass'] &= ref['stress']['pass']
            return ref
        shear = units.to_si(case['boundaries']['x1']['force'])
        mu = case['contacts']['interface'].get('mu',.2)
        metrics['contact_shear_n'] = abs(contact['force_n'][0])
        return comparison(case,'contact_shear',metrics['contact_shear_n'],min(shear,mu*pressure*area),'N','Coulomb block on a soft spring: T = min(tau A, mu p A)')
    x,u,s = mesh['nodes'],r['u'],r['s']
    if tid == 'large-cantilever':
        if case['boundaries']['x0']['role'] != 'beam-clamp' or case['boundaries']['x1']['role'] != 'load' or case['boundaries']['x1'].get('direction') != '-z':
            return na
        L,w,h = (units.to_si(p[k]) for k in ('length','width','height'))
        force = units.to_si(case['boundaries']['x1']['force'])
        if abs(force*L*L/(E*w*h**3/12)-1)>.0001:
            return na
        end = np.unique(mesh['face_x1'])
        metrics['tip_disp_m'] = float(-u[end,2].mean())
        metrics['horizontal_disp_m'] = float(-u[end,0].mean())
        ref = comparison(case,'tip_disp',metrics['tip_disp_m'],.3017*L,'m','Euler elastica, inextensible, PL²/EI = 1; vertical delta/L = 0.3017 (linear: 1/3)')
        ref['horizontal'] = comparison(case,'horizontal_disp',metrics['horizontal_disp_m'],.0566*L,'m','Elastica: horizontal shortening/L = 0.0566')
        ref['pass'] &= ref['horizontal']['pass']
        return ref
    if tid == 'rubber-tension':
        L = units.to_si(p['height']); stretch = 1+units.to_si(case['boundaries']['z1']['uz'])/L
        if props.get('model') != 'neo-hookean':
            return na
        expected = rubber_uniaxial(E,nu,stretch)
        metrics['axial_stress_pa'] = float(s[:,2].mean())
        return comparison(case,'axial_stress',metrics['axial_stress_pa'],expected['cauchy_pa'],'Pa','Homogeneous compressible neo-Hookean tension, lateral stress = 0; W = mu/2 (I1-3) - mu ln J + lambda/2 (ln J)²')
    if tid == 'plastic-bar':
        # The loading maximum and the subsequent zero-displacement state are both retained, not inferred from a formula.
        if not r.get('steps') or props.get('model') != 'elastoplastic':
            return na
        peak = max(zip(r['curve'],r['steps']),key=lambda x:x[0]['load_fraction'])[1]
        strain = units.to_si(case['boundaries']['x1']['ux'])/units.to_si(p['length'])
        expected = props['sy']+props['H']*(strain-props['sy']/E)
        if strain <= props['sy']/E:
            return na
        metrics['axial_stress_pa'] = float(peak['s'][:,0].mean())
        metrics['plastic_strain'] = float(peak['peeq'].mean())
        ref = comparison(case,'axial_stress',metrics['axial_stress_pa'],expected,'Pa','Bilinear hardening, uniaxial: sigma = sy + H (epsilon - sy/E)')
        ref['plastic_strain'] = comparison(case,'plastic_strain',metrics['plastic_strain'],strain-expected/E,'-','Uniaxial plastic strain: epsilon_p = epsilon - sigma/E')
        ref['pass'] &= ref['plastic_strain']['pass']
        return ref
    L,w,h = (units.to_si(p[k]) for k in ('length','width','height'))
    if props.get('model') != 'elastoplastic' or props.get('H') != 0:
        return na
    expected = props['sy']*w*h*h/(4*L)
    metrics['limit_load_n'] = r['curve'][-1]['load_fraction']*units.to_si(case['boundaries']['x1']['force'])
    return comparison(case,'limit_load',metrics['limit_load_n'],expected,'N','Perfectly plastic rectangular section, shear neglected: P = sy b h²/(4 L); last converged increment')
