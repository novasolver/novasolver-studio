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


class Constraints:
    def __init__(self, records, ndof, stiffness):
        self.records = records
        self.count = sum(len(r['master']) for r in records)
        self.area = np.concatenate([r['area'] for r in records]) if records else np.empty(0)
        self.g0 = np.concatenate([np.full(len(r['master']),r['g0']) for r in records]) if records else np.empty(0)
        self.mu = np.concatenate([np.full(len(r['master']),r['mu'] if r['type'] == 'frictional' else 0) for r in records]) if records else np.empty(0)
        self.bilateral = np.concatenate([np.full(len(r['master']),r['type'] == 'no-separation') for r in records]) if records else np.empty(0,bool)
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
        self.basis = np.concatenate(bases) if bases else np.empty((0,3,3))
        self.B = sp.csr_matrix((values,(rows,cols)),shape=(3*self.count,ndof))
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
        self.integrals = np.asarray(self.integrals)
        R = sp.bsr_matrix((self.basis,np.arange(self.count),np.arange(self.count+1)),shape=(3*self.count,3*self.count)).tocsr()
        mass = sp.kron(sp.block_diag(masses,format='csr'),sp.eye(3),format='csr') if masses else sp.csr_matrix((0,0))
        # Unknowns are nodal tractions times positive dual areas. Integrate their tri6 field
        # consistently into bulk nodal forces; a uniform pressure has zero corner *force*,
        # while its corner pressure is positive. Coulomb acts on pressure, not on that zero force.
        self.force_pairs = mass@R.T@sp.diags(np.repeat(1/self.area,3))
        self.G = (R.T@self.B).T@self.force_pairs
        self.slip_reference = np.zeros((self.count,2))
        self.blocked = np.zeros((self.count,3),bool)
        # An active-set scaling, not a penalty approximation: the converged equations are exact constraints.
        self.rho = stiffness

    def equations(self, u, lam, offset_scale=1.):
        d = (self.B@u).reshape(-1,3)
        g = d[:,0]+self.g0*offset_scale
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
            if radius > 0 and norm <= radius:
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
            sl = slice(start,start+len(rec['master']))
            pressure = l[sl,0]/self.area[sl]
            for side in ('master','slave'):
                idx = rec[side]
                fields['p_contact'][idx] = pressure
                fields['contact_gap'][idx] = gap[sl]
                fields['contact_slip'][idx] = np.linalg.norm(slip[sl],axis=1)
                fields['contact_status'][idx] = status[sl]
            force = (self.force_pairs@lam).reshape(-1,3)[sl].sum(0)
            normal_force = float(np.sum(pressure*self.integrals[sl]))
            interfaces[rec['face']] = {'force_n':force.tolist(), 'normal_force_n':normal_force,
                'pressure_pa':normal_force/float(self.area[sl].sum()),
                'status_counts':{k:int(np.sum(status[sl] == j)) for j,k in enumerate(('open','stick','slip'))},
                'gap_m':gap[sl].tolist(),'slip_m':np.linalg.norm(slip[sl],axis=1).tolist()}
            start = sl.stop
        # Natural-map residual in force units, relative to the largest nodal contact force.
        residual = self.equations(u,lam,scale)[0]
        comp = float(np.max(np.abs(residual))*self.rho/max(np.max(np.abs(lam)),1e-30)) if len(lam) else 0.
        return fields, interfaces, comp
