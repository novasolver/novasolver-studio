"""Conformal, touching interfaces: split topology at run time, never in the CAD mesh."""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp

from . import fem_tet10 as fem, units
from .store import StudioError


TYPES = ('bonded', 'frictionless', 'frictional', 'no-separation')


def settings(case, face):
    return {'type': 'bonded', 'mu': .2, 'offset': {'value': 0, 'unit': 'mm'},
            **case.get('contacts', {}).get(face, {})}


def split_mesh(case, mesh):
    """Duplicate once per (body, node), including exterior triangles sharing an interface edge.
    The four subtriangles' barycentric dual regions give A/12 to corners, A/4 to midsides.
    Curved faces use the same positive dual rule, rescaled to the tri6 quadrature area.
    """
    from .structural import surface_rule
    faces = {f['key']: f for f in case['geometry'].get('faces', [])}
    selected = [f for f in faces.values() if f.get('interface') and settings(case, f['key'])['type'] != 'bonded']
    if not selected:
        return mesh, []
    out = {k: v.copy() for k, v in mesh.items()}
    nodes, tets, bodies = mesh['nodes'], mesh['tets'], mesh['tet_body']
    maps, extra, parent = {}, [], {}
    selected_nodes = set()
    for f in selected:
        for node in np.unique(mesh['face_'+f['key']]):
            selected_nodes.add(int(node))
            for body in f['bodies']:
                key = int(node),int(body[1:]); parent[key] = key
    def root(key):
        parent.setdefault(key,key)
        if parent[key] != key:
            parent[key] = root(parent[key])
        return parent[key]
    for f in faces.values():
        if f.get('interface') and settings(case,f['key'])['type'] == 'bonded':
            a,b = (int(k[1:]) for k in f['bodies'])
            for node in selected_nodes.intersection(np.unique(mesh['face_'+f['key']])):
                ra,rb = root((node,a)),root((node,b))
                parent[max(ra,rb)] = min(ra,rb)
    assigned,original = {},set()
    for key in sorted(parent):
        node,body = key; group = root(key)
        if group not in assigned:
            assigned[group] = node if node not in original else len(nodes)+len(extra)
            if node in original:
                extra.append(nodes[node])
            original.add(node)
        maps.setdefault(body,{})[node] = assigned[group]
    out['nodes'] = np.vstack([nodes,np.asarray(extra).reshape(-1,3)])
    owner = {}
    for c in ((0,1,2),(0,1,3),(0,2,3),(1,2,3)):
        for row,body in zip(tets[:,c],bodies):
            owner[tuple(sorted(row))] = int(body)
    for body, mapping in maps.items():
        lookup = np.arange(len(nodes))
        for old, new in mapping.items():
            lookup[old] = new
        idx = bodies == body
        out['tets'][idx] = lookup[tets[idx]]
        for key, f in faces.items():
            if not f.get('interface') and 'face_'+key in out:
                tri = mesh['face_'+key]
                hit = np.array([owner.get(tuple(sorted(row[:3]))) == body for row in tri])
                out['face_'+key][hit] = lookup[tri[hit]]
            elif f.get('interface') and settings(case,key)['type'] == 'bonded' and int(f['bodies'][0][1:]) == body:
                out['face_'+key] = lookup[mesh['face_'+key]]
    records = []
    for f in selected:
        key = f['key']
        a, b = sorted(int(b[1:]) for b in f['bodies'])
        tri = mesh['face_'+key]
        master = np.unique(tri)
        # Both sides may already have been split by another interface at a triple junction.
        ma = np.array([maps.get(a, {}).get(int(i), int(i)) for i in master])
        slave = np.array([maps[b][int(i)] for i in master])
        normal = fem.outward_normals(nodes, tets[bodies == a], tri)
        _, weight, shape = surface_rule(nodes, tri)
        area = weight.sum(1)
        tributary = np.zeros(len(nodes)); nv = np.zeros((len(nodes), 3))
        for i, fraction in enumerate((1/12, 1/12, 1/12, 1/4, 1/4, 1/4)):
            np.add.at(tributary, tri[:, i], area*fraction)
            np.add.at(nv, tri[:, i], normal*(area*fraction)[:, None])
        n = nv[master]; n /= np.linalg.norm(n, axis=1)[:, None]
        cfg = settings(case, key)
        records.append({'face': key, 'bodies': [a,b], 'master': ma, 'slave': slave, 'normal': n,
                        'area': tributary[master], 'type': cfg['type'], 'mu': cfg['mu'],
                        'g0': -units.to_si(cfg['offset']),
                        'pressure_tri':np.searchsorted(master,tri),
                        'pressure_mass':np.einsum('eq,qi,qj->eij',weight,shape,shape)})
        for label, body in (('master',a),('slave',b)):
            out['contact_'+label+'_'+key] = np.array([[maps.get(body, {}).get(int(i),int(i)) for i in row] for row in tri])
        out['face_'+key] = out['contact_master_'+key]
        out['face_'+key+'__slave'] = out['contact_slave_'+key]
    return out, records


# ---------------------------------------------------------------- separate surfaces (contact_pairs): averaged-gap mortar

PAIR_TYPES = ('bonded', 'frictionless', 'frictional', 'no-separation')


def pair_settings(pair):
    return {'type': 'bonded', 'mu': .2, 'search': {'value': 1, 'unit': 'mm'}, **pair}


def _sub_rule(n=4):
    """Quadrature on the four sub-triangles of the tri6 parent (corner, corner, corner, middle). Returns parametric
    points (Q,2), weights on the parent (sum 1/2) and the piecewise-linear hats psi (Q,6) of the sub-triangle mesh,
    whose integrals are A/12 at corners and A/4 at midsides: the same positive dual areas the conformal contact uses."""
    x, w = np.polynomial.legendre.leggauss(n)
    x, w = (x + 1) / 2, w / 2
    ref = np.array([[0, 0], [1, 0], [0, 1], [.5, 0], [.5, .5], [0, .5]])
    subs = [(0, 3, 5), (3, 1, 4), (5, 4, 2), (3, 4, 5)]
    P, W, H = [], [], []
    for s in subs:
        A = ref[list(s)]
        for i, a in enumerate(x):
            for j, b in enumerate(x):
                l1, l2 = a, (1 - a) * b                    # collapsed (Duffy) coordinates on the sub-triangle
                l0 = 1 - l1 - l2
                P.append(l0 * A[0] + l1 * A[1] + l2 * A[2])
                W.append(w[i] * w[j] * (1 - a) * 0.25)     # each sub-triangle is a quarter of the parent
                h = np.zeros(6)
                h[list(s)] = (l0, l1, l2)
                H.append(h)
    return np.array(P), np.array(W), np.array(H)


def _tri6(xi, eta):
    """tri6 shape functions and parametric derivatives (Gmsh order: 3 corners, then edges 01, 12, 20)."""
    L = np.stack([1 - xi - eta, xi, eta], -1)
    N = np.concatenate([L * (2 * L - 1), 4 * L[..., [0]] * L[..., [1]], 4 * L[..., [1]] * L[..., [2]],
                        4 * L[..., [2]] * L[..., [0]]], -1)
    dL = np.array([[-1, 1, 0], [-1, 0, 1]], float)    # d(L0,L1,L2)/d(xi,eta)
    def d(k):
        a = dL[k]
        return np.concatenate([a * (4 * L - 1),
                               4 * (a[0] * L[..., [1]] + L[..., [0]] * a[1]),
                               4 * (a[1] * L[..., [2]] + L[..., [1]] * a[2]),
                               4 * (a[2] * L[..., [0]] + L[..., [2]] * a[0])], -1)
    return N, d(0), d(1)


def _project(points, dirs, Xm, search, candidates=8):
    """Project each point along its direction onto the master tri6 surface: x_m(xi, eta) = p + t d. Returns the
    master element, (xi, eta) and t of the nearest hit within `search` (element -1 where there is none)."""
    from scipy.spatial import cKDTree
    centre = Xm[:, :3].mean(1)
    size = np.linalg.norm(Xm[:, :3] - centre[:, None], axis=2).max(1)
    tree = cKDTree(centre)
    k = min(candidates, len(Xm))
    _, cand = tree.query(points, k=k)
    cand = cand.reshape(len(points), k)
    best_e = np.full(len(points), -1); best_t = np.full(len(points), np.inf); best_xi = np.zeros((len(points), 2))
    for c in range(k):
        e = cand[:, c]
        X = Xm[e]                                          # (P,6,3)
        xi = np.full((len(points), 2), 1 / 3); t = np.zeros(len(points))
        for _ in range(8):                                 # Newton on F = x_m(xi) - p - t d
            N, d1, d2 = _tri6(xi[:, 0], xi[:, 1])
            F = np.einsum('pi,pij->pj', N, X) - points - t[:, None] * dirs
            J = np.stack([np.einsum('pi,pij->pj', d1, X), np.einsum('pi,pij->pj', d2, X), -dirs], -1)
            step = np.linalg.solve(J + 1e-30 * np.eye(3), -F[..., None])[..., 0]
            xi += step[:, :2]; t += step[:, 2]
        tol = 1e-6
        inside = (xi[:, 0] >= -tol) & (xi[:, 1] >= -tol) & (xi.sum(1) <= 1 + tol) & (np.abs(t) <= search) & \
                 (np.linalg.norm(points - centre[e], axis=1) <= size[e] + search * 2 + 1e-12)
        better = inside & (np.abs(t) < np.abs(best_t))
        best_e[better], best_t[better], best_xi[better] = e[better], t[better], xi[better]
    return best_e, best_xi, best_t


def mortar_pairs(case, mesh):
    """Constraint records for contact_pairs between surfaces that share no nodes. For each slave node i the averaged
    jump J_i = (1/A_i) int psi_i (u_s - u_m(p(x))) dA is held in the contact laws, where p projects the slave point
    along the slave normal onto the master surface (small sliding: once, in the initial configuration)."""
    pairs = case.get('contact_pairs', {})
    if not pairs:
        return []
    nodes, tets = mesh['nodes'], mesh['tets']
    ndof = 3 * len(nodes)
    Q, W, H = _sub_rule(6)
    Ns, d1s, d2s = _tri6(Q[:, 0], Q[:, 1])
    records = []
    for name, raw in sorted(pairs.items()):
        cfg = pair_settings(raw)
        if set(cfg['master']) & set(cfg['slave']):
            raise StudioError('err.contact_pair_same_face', 400, pair=name)
        tri_m = np.concatenate([mesh['face_' + f] for f in cfg['master']])
        tri_s = np.concatenate([mesh['face_' + f] for f in cfg['slave']])
        if np.intersect1d(np.unique(tri_m), np.unique(tri_s)).size:
            raise StudioError('err.contact_pair_shared_nodes', 400, pair=name)
        search = units.to_si(cfg['search'])
        Xs = nodes[tri_s]                                   # (S,6,3)
        pts = np.einsum('qi,sij->sqj', Ns, Xs)              # (S,Q,3)
        t1 = np.einsum('qi,sij->sqj', d1s, Xs); t2 = np.einsum('qi,sij->sqj', d2s, Xs)
        cr = np.cross(t1, t2)
        jac = np.linalg.norm(cr, axis=2)
        ns = cr / jac[..., None]
        out = fem.outward_normals(nodes, tets, tri_s)       # orient the parametric normal outward
        ns *= np.sign(np.einsum('sqj,sj->sq', ns, out))[..., None]
        w = W[None, :] * jac                                # (S,Q) area weights
        e, xi, t = _project(pts.reshape(-1, 3), ns.reshape(-1, 3), nodes[tri_m], search)
        hit = (e >= 0).reshape(w.shape)
        slave = np.unique(tri_s)
        local = {int(n): i for i, n in enumerate(slave)}
        A = np.zeros(len(slave)); nsum = np.zeros((len(slave), 3)); gsum = np.zeros(len(slave))
        rows, cols, vals = [], [], []
        Nm = np.zeros((len(e), 6))
        if hit.any():
            Nm[e >= 0] = _tri6(xi[e >= 0, 0], xi[e >= 0, 1])[0]
        Nm = Nm.reshape(len(tri_s), len(Q), 6)
        em = e.reshape(w.shape); tq = np.where(e >= 0, t, 0.).reshape(w.shape)   # a miss has t = inf (0 * inf = nan)
        for a in range(6):                                  # weight node a of each slave element with psi_a
            ia = np.array([local[int(n)] for n in tri_s[:, a]])
            wa = w * H[None, :, a] * hit                    # (S,Q)
            np.add.at(A, ia, wa.sum(1))
            np.add.at(nsum, ia, np.einsum('sq,sqj->sj', wa, ns))
            np.add.at(gsum, ia, (wa * tq).sum(1))
            for b in range(6):                              # slave side
                rows.append(ia); cols.append(tri_s[:, b]); vals.append((wa * Ns[None, :, b]).sum(1))
            for b in range(6):                              # master side, at the projected points
                mnode = np.where(em >= 0, tri_m[np.maximum(em, 0), b], 0)
                rows.append(np.repeat(ia, len(Q))); cols.append(mnode.ravel()); vals.append(-(wa * Nm[:, :, b]).ravel())
        keep = A > 1e-12 * max(A.max(initial=0), 1e-300)
        if not keep.any():
            records.append({'face': name, 'no_contact': True, 'closest_m': float(np.abs(t[np.isfinite(t)]).min()) if np.isfinite(t).any() else None})
            continue
        r = np.concatenate(rows); c = np.concatenate(cols); v = np.concatenate(vals)
        S = sp.csr_matrix((v, (r, c)), shape=(len(slave), len(nodes)))
        S = sp.diags(np.where(keep, 1 / np.where(keep, A, 1), 0)) @ S
        S = S[keep]
        n = -nsum[keep] / np.linalg.norm(nsum[keep], axis=1)[:, None]   # master-side normal: slave moving along -n closes
        J = sp.kron(S, sp.eye(3), format='csr')           # world components, rows 3i..3i+2
        body = mesh.get('tet_body')
        def owner(tri):
            if body is None:
                return 0
            hits = np.isin(tets[:, :4], tri[0, :3]).sum(1) == 3
            return int(body[np.flatnonzero(hits)[0]])
        bilateral = cfg['type'] in ('bonded', 'no-separation')
        records.append({'face': name, 'bodies': [owner(tri_m), owner(tri_s)], 'master': np.unique(tri_m),
                        'slave': slave[keep], 'normal': n, 'area': A[keep], 'type': cfg['type'], 'mu': cfg['mu'],
                        'g0': np.zeros(int(keep.sum())) if cfg['type'] == 'bonded' else gsum[keep] / A[keep],
                        'J': J, 'tied': cfg['type'] == 'bonded', 'bilateral': bilateral})
    return records


def detect(case, mesh, search):
    """Candidate contact_pairs: faces of different bodies, no shared nodes, closer than `search` with facing normals
    (n_a . n_b < -0.9 where they are close). The side with the smaller elements is the slave."""
    from scipy.spatial import cKDTree
    nodes, tets = mesh['nodes'], mesh['tets']
    desc = {f['key']: f for f in case['geometry'].get('faces', []) if not f.get('interface')}
    info = {}
    for key, f in desc.items():
        tri = mesh.get('face_' + key)
        if tri is None or not len(tri) or len(f.get('bodies', [])) != 1:
            continue
        c = nodes[tri[:, :3]].mean(1)
        info[key] = {'tri': tri, 'c': c, 'n': fem.outward_normals(nodes, tets, tri), 'body': f['bodies'][0],
                     'edge': float(np.linalg.norm(nodes[tri[:, 0]] - nodes[tri[:, 1]], axis=1).mean()),
                     'nodes': set(np.unique(tri).tolist()), 'tree': cKDTree(c)}
    out, keys = [], sorted(info)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            A, Bf = info[a], info[b]
            if A['body'] == Bf['body'] or A['nodes'] & Bf['nodes']:
                continue
            reach = search + max(A['edge'], Bf['edge'])        # centroids of facing elements are up to an edge apart
            d, j = Bf['tree'].query(A['c'], distance_upper_bound=reach)
            close = np.isfinite(d)
            if not close.any():
                continue
            facing = close.copy()
            facing[close] = np.einsum('ij,ij->i', A['n'][close], Bf['n'][j[close]]) < -0.9
            # the normal distance between the facing elements, not the centroid distance, must be within search
            gap = np.full(len(d), np.inf)
            gap[facing] = np.abs(np.einsum('ij,ij->i', Bf['c'][j[facing]] - A['c'][facing], A['n'][facing]))
            hit = facing & (gap <= search)
            if hit.sum() < max(3, 0.05 * len(A['c'])):
                continue
            slave, master = (a, b) if A['edge'] <= Bf['edge'] else (b, a)
            out.append({'master': [master], 'slave': [slave], 'gap_m': float(gap[hit].min()),
                        'coverage': float(hit.mean())})
    return out


class Constraints:
    def __init__(self, records, ndof, stiffness):
        # conformal node pairs first, then the mortar pairs of separate surfaces (each with its own operator J)
        records = [r for r in records if 'J' not in r and not r.get('no_contact')] + [r for r in records if 'J' in r]
        self.records = records
        mortar = [r for r in records if 'J' in r]
        records = [r for r in records if 'J' not in r]
        everything = self.records
        self.count = sum(len(r['slave'] if 'J' in r else r['master']) for r in everything)
        size = lambda r: len(r['slave'] if 'J' in r else r['master'])
        self.area = np.concatenate([r['area'] for r in everything]) if everything else np.empty(0)
        self.g0 = np.concatenate([np.broadcast_to(r['g0'], size(r)).astype(float) for r in everything]) if everything else np.empty(0)
        self.mu = np.concatenate([np.full(size(r),r['mu'] if r['type'] == 'frictional' else 0) for r in everything]) if everything else np.empty(0)
        self.bilateral = np.concatenate([np.full(size(r),r['type'] in ('no-separation','bonded')) for r in everything]) if everything else np.empty(0,bool)
        self.tied = np.concatenate([np.full(size(r),bool(r.get('tied'))) for r in everything]) if everything else np.empty(0,bool)
        # conformal offsets (press-fit interference) are ramped with the load; a mortar pair's measured gap is not
        self.ramped = np.concatenate([np.full(size(r),'J' not in r) for r in everything]) if everything else np.empty(0,bool)
        rows, cols, values, bases = [], [], [], []
        start = 0
        for r in records:
            n = r['normal']
            axis = np.eye(3)[np.argmin(np.abs(n),axis=1)]
            t = np.cross(n,axis); t /= np.linalg.norm(t,axis=1)[:,None]
            basis = np.stack([n,t,np.cross(n,t)],axis=1)
            bases.append(basis)
            for side, sign in (('slave',1),('master',-1)):
                rows.extend(np.broadcast_to(3*np.arange(start,start+len(n))[:,None,None]+np.arange(3)[None,:,None],basis.shape).ravel())
                cols.extend(np.broadcast_to(3*r[side][:,None,None]+np.arange(3)[None,None,:],basis.shape).ravel())
                values.extend((sign*basis).ravel())
            start += len(n)
        cc = start                                      # conformal pairs; the mortar rows follow
        mbases = []
        for r in mortar:
            n = r['normal']
            axis = np.eye(3)[np.argmin(np.abs(n),axis=1)]
            t = np.cross(n,axis); t /= np.linalg.norm(t,axis=1)[:,None]
            mbases.append(np.stack([n,t,np.cross(n,t)],axis=1))
        self.basis = np.concatenate(bases+mbases) if bases or mbases else np.empty((0,3,3))
        Bc = sp.csr_matrix((values,(rows,cols)),shape=(3*cc,ndof))
        masses = []
        self.integrals = []
        for rec in records:
            size = len(rec['master'])
            if 'pressure_mass' in rec:
                tri = rec['pressure_tri']
                mass = sp.csr_matrix((rec['pressure_mass'].ravel(),(np.repeat(tri,6,axis=1).ravel(),np.tile(tri,(1,6)).ravel())),shape=(size,size))
            else:
                mass = sp.diags(rec['area'])
            masses.append(mass)
            self.integrals.extend(np.asarray(mass.sum(0)).ravel())
        for rec in mortar:
            self.integrals.extend(rec['area'])
        self.integrals = np.asarray(self.integrals)
        def rotation(b):
            return sp.bsr_matrix((b,np.arange(len(b)),np.arange(len(b)+1)),shape=(3*len(b),3*len(b))).tocsr()
        Rc = rotation(self.basis[:cc])
        mass = sp.kron(sp.block_diag(masses,format='csr'),sp.eye(3),format='csr') if masses else sp.csr_matrix((0,0))
        # Unknowns are nodal tractions times positive dual areas. Integrate their tri6 field
        # consistently into bulk nodal forces; a uniform pressure has zero corner *force*,
        # while its corner pressure is positive. Coulomb acts on pressure, not on that zero force.
        fc = mass@Rc.T@sp.diags(np.repeat(1/self.area[:cc],3)) if cc else sp.csr_matrix((0,0))
        Gc = ((Rc.T@Bc).T@fc) if cc else sp.csr_matrix((ndof,0))
        # Mortar: lambda_i is the traction times A_i in the local basis. The work of the averaged jump gives the
        # nodal forces B^T lambda directly, and the force on the slave side is R^T lambda.
        Rm = rotation(self.basis[cc:]) if mortar else sp.csr_matrix((0,0))
        Bm = (Rm@sp.vstack([r['J'] for r in mortar],format='csr')) if mortar else sp.csr_matrix((0,ndof))
        self.B = sp.vstack([Bc,Bm],format='csr')
        self.force_pairs = sp.block_diag([fc,Rm.T],format='csr') if cc and mortar else (fc if cc else Rm.T.tocsr())
        self.G = sp.hstack([Gc,Bm.T],format='csr')
        self.slip_reference = np.zeros((self.count,2))
        self.blocked = np.zeros((self.count,3),bool)
        # An active-set scaling, not a penalty approximation: the converged equations are exact constraints.
        self.rho = stiffness

    def equations(self, u, lam, offset_scale=1.):
        d = (self.B@u).reshape(-1,3)
        g = d[:,0]+self.g0*np.where(self.ramped,offset_scale,1.)   # a real gap is there from the start
        l = lam.reshape(-1,3)
        r = self.rho
        trial = l[:,0]-r*g
        active = (trial >= 0)|self.bilateral
        p = np.where(self.bilateral,trial,np.maximum(trial,0))
        residual = np.zeros_like(l)
        Du = np.zeros((self.count,3,3)); Dl = np.broadcast_to(np.eye(3)/r,(self.count,3,3)).copy()
        residual[:,0] = np.where(active,g,l[:,0]/r)
        Du[active,0,0] = 1.; Dl[active,0,0] = 0.
        status = np.where(active,1,0)
        for i in range(self.count):
            increment = d[i,1:]-self.slip_reference[i]
            z = l[i,1:]-r*increment
            radius = self.mu[i]*max(p[i],0)
            norm = np.linalg.norm(z)
            if self.tied[i]:                            # bonded separate parts: no slip, whatever the pressure
                residual[i,1:] = increment
                Du[i,1:,1:] = np.eye(2); Dl[i,1:,1:] = 0
            elif radius > 0 and norm <= radius:
                residual[i,1:] = increment
                Du[i,1:,1:] = np.eye(2); Dl[i,1:,1:] = 0
            elif radius > 0 and norm > radius:
                v = z/norm
                proj = radius/norm*(np.eye(2)-np.outer(v,v))
                residual[i,1:] = (l[i,1:]-radius*v)/r
                Du[i,1:,1:] = proj
                Du[i,1:,0] = self.mu[i]*v
                Dl[i,1:,1:] -= proj/r
                Dl[i,1:,0] = -self.mu[i]*v/r
                status[i] = 2
            else:
                residual[i,1:] = l[i,1:]/r
            for c in (1,2):
                if self.blocked[i,c] and status[i] != 2:
                    # A symmetry plane may already fix this component on both sides. Its contact
                    # multiplier is indeterminate; do not add a second copy of the same constraint.
                    residual[i,c] = l[i,c]/r
                    Du[i,c] = 0; Dl[i,c] = 0; Dl[i,c,c] = 1/r
            if self.blocked[i,0] and abs(g[i])<1e-14:
                residual[i,0] = l[i,0]/r
                Du[i,0] = 0; Dl[i,0] = 0; Dl[i,0,0] = 1/r
        def blocks(a):
            return sp.bsr_matrix((a,np.arange(self.count),np.arange(self.count+1)),shape=(3*self.count,3*self.count)).tocsr()
        return residual.ravel(), blocks(Du)@self.B, blocks(Dl), status, g, d[:,1:]

    def commit(self,u,lam,scale):
        *_,status,gap,slip = self.equations(u,lam,scale)
        moving = status != 1
        self.slip_reference[moving] = slip[moving]

    def fields(self, u, lam, scale=1.):
        _, _, _, status, gap, slip = self.equations(u,lam,scale)
        n = len(u)//3
        fields = {k:np.zeros(n) for k in ('p_contact','contact_gap','contact_slip','contact_status')}
        interfaces = {}; start = 0
        l = lam.reshape(-1,3)
        for rec in self.records:
            mortar = 'J' in rec
            sl = slice(start,start+len(rec['slave' if mortar else 'master']))
            pressure = l[sl,0]/self.area[sl]
            for side in (('slave',) if mortar else ('master','slave')):   # mortar values live on the slave nodes
                idx = rec[side]
                fields['p_contact'][idx] = pressure
                fields['contact_gap'][idx] = gap[sl]
                fields['contact_slip'][idx] = np.linalg.norm(slip[sl],axis=1)
                fields['contact_status'][idx] = status[sl]
            force = (self.force_pairs@lam).reshape(-1,3)[sl].sum(0)
            normal_force = float(np.sum(pressure*self.integrals[sl]))
            if mortar:
                # the averaged-gap constraint has no "inside" sign of its own: the compressive force is l_n
                normal_force = float(np.sum(l[sl,0]))
            interfaces[rec['face']] = {'force_n':force.tolist(), 'normal_force_n':normal_force,
                'pressure_pa':normal_force/float(self.area[sl].sum()),
                'status_counts':{k:int(np.sum(status[sl] == j)) for j,k in enumerate(('open','stick','slip'))},
                'gap_m':gap[sl].tolist(),'slip_m':np.linalg.norm(slip[sl],axis=1).tolist()}
            start = sl.stop
        # Natural-map residual in force units, relative to the largest nodal contact force.
        residual = self.equations(u,lam,scale)[0]
        comp = float(np.max(np.abs(residual))*self.rho/max(np.max(np.abs(lam)),1e-30)) if len(lam) else 0.
        return fields, interfaces, comp
