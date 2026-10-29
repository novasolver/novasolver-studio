"""Conforming Kuhn tetrahedra on a rectangular grid, elevated to tet10.

Long verification beams need directional resolution without meshing the whole length at the
through-thickness size. Exterior tri6 and element ordering are identical to the Gmsh interface.
"""
from __future__ import annotations

from itertools import permutations
import numpy as np

from .fem_tet10 import EDGES


def generate(size,divisions):
    axes = [np.linspace(0,s,n+1) for s,n in zip(size,divisions)]
    xyz = np.stack(np.meshgrid(*axes,indexing='ij'),axis=-1).reshape(-1,3)
    nodes = xyz.tolist()
    grid = np.arange(len(nodes)).reshape(tuple(n+1 for n in divisions))
    corners = []
    for base in np.ndindex(*divisions):
        for order in permutations(range(3)):
            point = np.array(base); cell = [grid[tuple(point)]]
            for axis in order:
                point[axis] += 1; cell.append(grid[tuple(point)])
            X = xyz[cell]
            if np.linalg.det((X[1:]-X[0]).T)<0:
                cell[1],cell[2] = cell[2],cell[1]
            corners.append(cell)
    edges = {}; tets = []
    for c in corners:
        mids = []
        for a,b in EDGES:
            pair = tuple(sorted((c[a],c[b])))
            if pair not in edges:
                edges[pair] = len(nodes)
                nodes.append(((np.array(nodes[pair[0]])+nodes[pair[1]])/2).tolist())
            mids.append(edges[pair])
        tets.append(c+mids)
    nodes = np.asarray(nodes); tets = np.asarray(tets,int)
    faces = {f'{a}{b}':[] for a in 'xyz' for b in '01'}
    for c in corners:
        for a,b,d in ((0,1,2),(0,1,3),(0,2,3),(1,2,3)):
            tri = [c[a],c[b],c[d]]; x = nodes[tri]
            for axis in range(3):
                for side in range(2):
                    if np.all(np.abs(x[:,axis]-side*size[axis])<1e-12):
                        faces['xyz'[axis]+str(side)].append(tri+[edges[tuple(sorted((tri[i],tri[j])))] for i,j in ((0,1),(1,2),(2,0))])
    return {'nodes':nodes,'tets':tets,**{'face_'+k:np.asarray(v,int) for k,v in faces.items()}}


DIVISIONS = {'large-cantilever':(64,4,2),'plastic-bar':(10,2,2),
             'plastic-beam-collapse':(32,2,6),'rubber-tension':(2,2,10)}


def write(case,folder):
    import json
    from .geometry import dims
    from .fem_tet10 import tri_areas
    from .results import _surface_from_mesh
    scale = {'coarse':.7,'normal':1.,'fine':1.5}[case['mesh']['size']]
    div = [max(1,int(round(n*scale))) for n in DIVISIONS[case['template']]]
    mesh = generate(dims(case),div)
    np.savez_compressed(folder/'mesh.npz',**mesh)
    display = {'bbox':[[0,0,0],dims(case)],'dims':dims(case),'faces':[],'info':case['geometry'].get('faces',[])}
    for i,key in enumerate(k for k in mesh if k.startswith('face_')):
        c = mesh[key]; a,b,d,ab,bd,da = c.T
        tri = np.stack([np.stack([a,ab,da],1),np.stack([ab,b,bd],1),np.stack([da,bd,d],1),np.stack([ab,bd,da],1)],1).reshape(-1,3)
        used,inv = np.unique(tri,return_inverse=True)
        display['faces'].append({'id':i,'key':key[5:],'positions':mesh['nodes'][used].ravel().tolist(),'indices':inv.ravel().tolist()})
    (folder/'display.json').write_text(json.dumps(display),encoding='utf-8')
    stats = {'nodes':len(mesh['nodes']),'elements':len(mesh['tets']),'element_type':'tet10','h':min(s/n for s,n in zip(dims(case),div))}
    (folder/'mesh_stats.json').write_text(json.dumps(stats),encoding='utf-8')
    return stats
