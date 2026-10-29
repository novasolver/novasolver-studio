"""CPU section caps: one field mesh and no stencil passes on integrated graphics."""
import numpy as np

from .store import StudioError


def section_field(jd, kind, quantity, mode, P, triangles, scalars, displacement, section,step=None):
    try:
        normal = np.asarray(section['normal'],float)
        position = float(section.get('position',.5))
        if normal.shape != (3,) or not np.isfinite(normal).all() or np.linalg.norm(normal) == 0 or not 0 <= position <= 1:
            raise ValueError()
        normal /= np.linalg.norm(normal)
    except (ValueError,TypeError,KeyError):
        raise StudioError('err.path',400,path='section')
    mesh,data = np.load(jd/'mesh.npz'),np.load(jd/'results.npz')
    if step is not None:
        class Fields(dict):
            @property
            def files(self): return list(self)
        data = Fields({k[5:] if k.startswith('step_') else k:data[k][step-1].copy() if k.startswith('step_') else data[k] for k in data.files})
    nodes = mesh['nodes']
    projected = nodes@normal
    offset = projected.min()+position*np.ptp(projected)
    # A section through a mesh node is nudged below it to avoid duplicate zero-area intersections.
    offset += max(np.ptp(projected),1e-12)*1e-9
    origin = offset*normal
    output, values, indices = [], [], []
    from .probe import _fields, _Locator
    if kind == 'modal':
        u = data['mode_shapes'][mode-1]
        nodal = np.column_stack([np.linalg.norm(u,axis=1),u])
    else:
        fields = _fields(kind,data)
        # Probe uses SI for electric fields, while the result colour bar uses display units.
        nodal = fields[quantity][0]
        if quantity in ('emag','jmag','q'):
            nodal = nodal/1e6
        nodal = np.column_stack([nodal,data['u']]) if displacement is not None else nodal[:,None]
    from .fem_tet10 import canonical_tets
    original = canonical_tets(nodes,mesh['tets']) if mesh['tets'].shape[1] == 10 else mesh['tets']
    locator = _Locator(nodes, original)
    def evaluate(point, owner=None):
        if owner is None:
            hit = locator.locate(point)
            if hit is None:
                raise StudioError('err.path',400,path='section interpolation')
            owner, L = hit[:2]
        else:
            L = locator.bary(owner, point)
        L = locator.curved(owner, point, L)
        idx, weights = locator.weights(owner, L)
        return weights@nodal[idx]
    bundle = np.column_stack([scalars,displacement]) if displacement is not None else scalars[:,None]
    for tri in triangles:
        poly = [(P[i],bundle[i]) for i in tri]
        clipped = []
        for i,(a,va) in enumerate(poly):
            b,vb = poly[(i+1)%3]
            da,db = a@normal-offset,b@normal-offset
            if da <= 0:
                clipped.append((a,va))
            if (da <= 0) != (db <= 0):
                t = da/(da-db)
                point = a+t*(b-a)
                clipped.append((point,evaluate(point)))
        base = len(output)
        output.extend(p for p,_ in clipped)
        values.extend(v for _,v in clipped)
        indices.extend([base,base+i,base+i+1] for i in range(1,len(clipped)-1))
    conn = original
    subdivisions = 1
    if conn.shape[1] == 10:
        sub = np.array([[0,4,6,7],[4,1,5,8],[6,5,2,9],[7,8,9,3],
                        [4,6,7,9],[4,6,5,9],[4,5,8,9],[4,7,8,9]])
        conn = conn[:,sub].reshape(-1,4)
        subdivisions = len(sub)
    from .flow3d import slice_plane
    cap,cap_tri,cap_values = slice_plane(nodes,conn,nodal,origin,normal,
        interpolate=lambda e, point: evaluate(point, e//subdivisions))
    if len(cap):
        indices.extend((cap_tri+len(output)).tolist())
        output.extend(cap)
        values.extend(cap_values)
    if not indices:
        raise StudioError('err.path',400,path='section does not intersect the result')
    values = np.asarray(values)
    return np.asarray(output),np.asarray(indices,int),values[:,0],values[:,1:] if displacement is not None else None
