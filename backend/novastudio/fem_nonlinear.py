"""Incremental tet10 mechanics, with trial state isolated from committed plastic history.

Linear materials use Green strain / second Piola stress for large deformation. The neo-Hookean
volumetric log J is projected to its element mean; its tangent includes the projection coupling.
Contact uses the Coulomb disk's natural map in this same Newton iteration.
"""
from __future__ import annotations

import warnings
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from . import fem_tet10 as fem
from .contact import Constraints
from .store import StudioError


def von_mises(s):
    return np.sqrt(.5*((s[...,0]-s[...,1])**2+(s[...,1]-s[...,2])**2+(s[...,2]-s[...,0])**2)
                   +3*np.sum(s[...,3:]**2,axis=-1))


def tensor(v, strain=False):
    a = np.zeros(v.shape[:-1]+(3,3))
    a[...,range(3),range(3)] = v[...,:3]
    for k,(i,j) in enumerate(((0,1),(1,2),(2,0)),3):
        a[...,i,j] = a[...,j,i] = v[...,k]*(.5 if strain else 1.)
    return a


def voigt(a, strain=False):
    return np.stack([a[...,0,0],a[...,1,1],a[...,2,2],a[...,0,1]*(2 if strain else 1),
                     a[...,1,2]*(2 if strain else 1),a[...,2,0]*(2 if strain else 1)],axis=-1)


def radial_return(strain, E, nu, sy, H, plastic, peeq):
    """Small strain J2; H is the requested post-yield uniaxial tangent, not the plastic modulus."""
    D = fem.elasticity_matrix(E,nu)
    mu = E/(2*(1+nu))
    hard = E*H/(E-H)
    trial = (strain-plastic)@D.T
    dev = trial.copy(); dev[...,:3] -= trial[...,:3].mean(axis=-1)[...,None]
    q = von_mises(trial)
    gamma = np.maximum(q-sy-hard*peeq,0)/(3*mu+hard)
    a = 1-3*mu*gamma/np.maximum(q,1e-30)
    stress = trial.copy(); stress += (a-1)[...,None]*dev
    flow = 1.5*dev/np.maximum(q[...,None],1e-30); flow[...,3:] *= 2
    new_plastic = plastic+gamma[...,None]*flow
    tangent = np.broadcast_to(D,strain.shape[:-1]+(6,6)).copy()
    active = gamma > 0
    if np.any(active):
        s,qq,aa,gg = dev[active],q[active],a[active],gamma[active]
        project = np.eye(6); project[:3,:3] -= 1/3
        dq = (1.5*s/qq[:,None]); dq[:,3:] *= 2
        dq = dq@D
        da = -3*mu*(1/(3*mu+hard)/qq-gg/qq**2)
        tangent[active] = D+(aa-1)[:,None,None]*(project@D)+s[:,:,None]*(da[:,None]*dq)[:,None,:]
    return stress,tangent,new_plastic,peeq+gamma


class Mechanics:
    def __init__(self,nodes,tets,groups,large=False,alpha=0.,temperature=None,T_ref=293.15):
        self.nodes,self.tets,self.groups,self.large = nodes,fem.canonical_tets(nodes,tets),groups,large
        self.dofs = (3*self.tets[:,:,None]+np.arange(3)).reshape(-1,30)
        self.expansion = np.zeros((len(tets),4))
        if temperature is not None:
            self.expansion = np.broadcast_to(alpha,len(tets))[:,None]*(np.broadcast_to(temperature,len(nodes))[self.tets]@fem.SHAPE.T-T_ref)
        self.ep = np.zeros((len(tets),4,6)); self.peeq = np.zeros((len(tets),4))
        self.grad = np.empty((len(tets),4,3,10)); self.w = np.empty((len(tets),4))
        X = nodes[self.tets]
        for g in range(4):
            J = np.einsum('ik,ekj->eij',fem.DSHAPE[g],X)
            self.grad[:,g] = np.linalg.solve(J,np.broadcast_to(fem.DSHAPE[g],(len(tets),3,10)))
            self.w[:,g] = fem.GW[g]*np.linalg.det(J)
        if np.any(self.w <= 0):
            raise ValueError('inverted reference element')
        for _,p in groups:
            model = p.get('model','linear')
            if model == 'elastoplastic' and large:
                raise StudioError('err.plastic_large',400)
            if model == 'neo-hookean' and not large:
                raise StudioError('err.neo_large',400)
            if model == 'elastoplastic' and not p.get('sy'):
                raise StudioError('err.plastic_sy',400)
        self.linear_system = None
        if not large and all(p.get('model','linear') == 'linear' for _,p in groups):
            Es,nus = np.empty(len(tets)),np.empty(len(tets))
            for idx,p in groups:
                Es[idx],nus[idx] = p['E'],p['nu']
            self.linear_system = fem.structural_system(nodes,self.tets,Es,nus,alpha,temperature,T_ref)[:2]

    def assemble(self,u,scale=1.,tangent=True):
        if self.linear_system is not None:
            K,initial = self.linear_system
            stresses = np.zeros((len(self.tets),4,6)); maximum = 0.
            for idx,p in self.groups:
                D = fem.elasticity_matrix(p['E'],p['nu'])
                for g in range(4):
                    strain = np.einsum('eki,ei->ek',fem._bmatrix(self.grad[idx,g]),u[self.dofs[idx]])
                    strain[:,:3] -= self.expansion[idx,g,None]*scale
                    stresses[idx,g] = strain@D.T
                    maximum = max(maximum,float(np.abs(strain).max()))
            return K,K@u-initial*scale,stresses,self.ep.copy(),self.peeq.copy(),maximum
        ndof = u.size
        K = sp.csr_matrix((ndof,ndof)); force = np.zeros(ndof)
        stresses = np.zeros((len(self.tets),4,6)); ep = self.ep.copy(); peeq = self.peeq.copy()
        max_strain = 0.
        # Bounded blocks; no tangent is retained from previous iterations.
        for indices,p in self.groups:
            for start in range(0,len(indices),1000):
                idx = indices[start:start+1000]
                grad,w = self.grad[idx],self.w[idx]
                ue = u[self.dofs[idx]].reshape(-1,10,3)
                F = np.eye(3)+np.einsum('eai,egJa->egiJ',ue,grad)
                model = p.get('model','linear')
                E,nu = p['E'],p['nu']; mu,lam = E/(2*(1+nu)),E*nu/((1+nu)*(1-2*nu))
                Ke = np.zeros((len(idx),30,30)); fe = np.zeros((len(idx),30))
                logj = None
                plastic_trace = None
                if model == 'elastoplastic':
                    # Plastic flow is incompressible even when elastic nu is moderate. An element
                    # pressure (B-bar) avoids artificial hardening from volumetric locking.
                    bulk = E/(3*(1-2*nu))
                    trace = np.trace(F,axis1=2,axis2=3)-3-3*self.expansion[idx]*scale
                    plastic_trace = np.sum(w*trace,axis=1)/w.sum(1)
                    if tangent:
                        mean_b = np.einsum('eg,egJa->eaJ',w,grad).reshape(-1,30)/w.sum(1)[:,None]
                        Ke += (bulk*w.sum(1))[:,None,None]*mean_b[:,:,None]*mean_b[:,None,:]
                if self.large:
                    det = np.linalg.det(F)
                    if np.any(det <= 0):
                        raise ValueError('inverted deformed element')
                    inv = np.swapaxes(np.linalg.inv(F),-1,-2)
                    if model == 'neo-hookean':
                        # Selective volumetric integration, exact on homogeneous deformations.
                        logj = (w*np.log(det)).sum(1)/w.sum(1)
                        if tangent:
                            mean_b = np.einsum('eg,egiJ,egJa->eai',w,inv,grad).reshape(-1,30)/w.sum(1)[:,None]
                            Ke += (lam*w.sum(1))[:,None,None]*mean_b[:,:,None]*mean_b[:,None,:]
                for g in range(4):
                    G = grad[:,g]; B = fem._bmatrix(G)
                    if self.large and model == 'neo-hookean':
                        fg,ig = F[:,g],inv[:,g]
                        # Isotropic thermal expansion acts on the elastic deformation gradient.
                        thermal = 1+self.expansion[idx,g]*scale
                        coeff = lam*(logj-3*np.log(thermal))-mu
                        P = mu*fg/thermal[:,None,None]**2+coeff[:,None,None]*ig
                        if tangent:
                            A = mu/thermal[:,None,None,None,None]**2*np.einsum('ik,JL->iJkL',np.eye(3),np.eye(3))[None]
                            A = A-coeff[:,None,None,None,None]*np.einsum('eiL,ekJ->eiJkL',ig,ig)
                            ke = np.einsum('eJa,eiJkL,eLb->eaibk',G,A,G,optimize=True).reshape(-1,30,30)
                            Ke += w[:,g,None,None]*ke
                        fe += w[:,g,None]*np.einsum('eiJ,eJa->eai',P,G).reshape(-1,30)
                        stresses[idx,g] = voigt(np.einsum('eiJ,ekJ->eik',P,fg)/det[:,g,None,None])
                        max_strain = max(max_strain,float(np.abs(fg-np.eye(3)).max()))
                        continue
                    if self.large:
                        fg = F[:,g]
                        strain = voigt(.5*(np.einsum('eki,ekj->eij',fg,fg)-np.eye(3)),True)
                        # derivative of Green strain w.r.t. each nodal displacement
                        B = np.empty((len(idx),6,10,3))
                        for a in range(3):
                            B[:,a] = G[:,a,:,None]*fg[:,:,a][:,None,:]
                        for a,(j,k) in enumerate(((0,1),(1,2),(2,0)),3):
                            B[:,a] = G[:,j,:,None]*fg[:,:,k][:,None,:]+G[:,k,:,None]*fg[:,:,j][:,None,:]
                        B = B.reshape(-1,6,30)
                    else:
                        strain = np.einsum('eki,ei->ek',B,u[self.dofs[idx]])
                    strain[:,:3] -= self.expansion[idx,g,None]*scale
                    max_strain = max(max_strain,float(np.abs(strain).max()))
                    if model == 'elastoplastic':
                        strain[:,:3] += (plastic_trace-strain[:,:3].sum(1))[:,None]/3
                        stress,D,ep[idx,g],peeq[idx,g] = radial_return(strain,E,nu,p['sy'],p.get('H',E/100),self.ep[idx,g],self.peeq[idx,g])
                        volumetric = np.array([1,1,1,0,0,0])
                        D -= bulk*np.outer(volumetric,volumetric)
                    else:
                        D = np.broadcast_to(fem.elasticity_matrix(E,nu),(len(idx),6,6))
                        stress = np.einsum('ekl,el->ek',D,strain)
                    if tangent:
                        Ke += w[:,g,None,None]*(B.transpose(0,2,1)@(D@B))
                    fe += w[:,g,None]*np.einsum('eki,ek->ei',B,stress)
                    if self.large:
                        S = tensor(stress)
                        if tangent:
                            geo = np.einsum('eJa,eJL,eLb->eab',G,S,G)
                            Ke += w[:,g,None,None]*np.einsum('eab,ik->eaibk',geo,np.eye(3)).reshape(-1,30,30)
                        stress = voigt(np.einsum('eiJ,eJL,ekL->eik',fg,S,fg)/det[:,g,None,None])
                    stresses[idx,g] = stress
                dofs = self.dofs[idx]
                if tangent:
                    K += sp.csr_matrix((Ke.ravel(),(np.repeat(dofs,30,axis=1).ravel(),np.tile(dofs,(1,30)).ravel())),shape=(ndof,ndof))
                np.add.at(force,dofs.ravel(),fe.ravel())
        return K,force,stresses,ep,peeq,max_strain


def linear_solve(A,b,contact=False,nprimal=None,near_null=None):
    if not len(b):
        return np.empty(0)
    with warnings.catch_warnings():
        warnings.simplefilter('error',spla.MatrixRankWarning)
        if (len(b) if nprimal is None else nprimal) <= fem.DIRECT_LIMIT:
            x = spla.spsolve(A.tocsc(),b,permc_spec='MMD_AT_PLUS_A')
        elif not contact:
            try:
                x = fem._amg_cg(A,b,B=near_null,tol=1e-10)
            except RuntimeError:
                if len(b)>fem.DIRECT_FALLBACK_LIMIT:
                    raise
                x = spla.spsolve(A.tocsc(),b,permc_spec='MMD_AT_PLUS_A')
        else:
            # The exact multiplier equations are indefinite (and slip is nonsymmetric). Use AMG-CG
            # on an augmented primal block inside GMRES, rather than applying CG to a saddle matrix.
            import pyamg
            n = nprimal
            K,G = A[:n,:n].tocsr(),A[:n,n:].tocsr()
            scale = max(float(np.abs(K.diagonal()).mean()),1e-30)
            augmented = K+(G@G.T)/scale
            hierarchy = pyamg.smoothed_aggregation_solver(augmented,symmetry='symmetric')
            diagonal = np.maximum(np.asarray(G.multiply(G).sum(0)).ravel()/scale+np.abs(A[n:,n:].diagonal()),scale*1e-12)
            def precondition(v):
                primal,info = spla.cg(augmented,v[:n],M=hierarchy.aspreconditioner(),rtol=1e-6,atol=0,maxiter=500)
                if info:
                    raise RuntimeError('AMG-CG contact primal solve did not converge')
                return np.r_[primal,v[n:]/diagonal]
            x,info = spla.gmres(A,b,M=spla.LinearOperator(A.shape,precondition),rtol=1e-9,atol=1e-12,restart=100,maxiter=500)
            if info:
                raise RuntimeError('contact tangent did not converge')
    if not np.all(np.isfinite(x)) or np.linalg.norm(A@x-b) > 1e-6*max(np.linalg.norm(b),1e-20):
        raise RuntimeError('singular tangent')
    return x


def solve(nodes,tets,groups,fixed_faces,tractions,rollers=(),prescribed=(),*,large=False,steps='auto',max_iterations=25,
          contact_pairs=(),rho=0.,acceleration=None,alpha=0.,temperature=None,T_ref=293.15,
          follower=None,progress=lambda *_:None,al_factor=1.,path=None,springs=None,face_nodes=(),nodal_forces=None):
    n = len(nodes); ndof = 3*n
    fem.check_memory(n,'nonlinear',(10 if steps == 'auto' else int(steps))*max(1,len(path or [])))
    mech = Mechanics(nodes,tets,groups,large,alpha,temperature,T_ref)
    tets = mech.tets
    fixed,rigid,_ = fem.modal_constraints(nodes,fixed_faces,rollers,tets)
    known = {int(i):0. for i in fixed}
    for tri,c,value in prescribed:
        for node in np.unique(tri):
            dof = 3*int(node)+c
            if dof in known and abs(known[dof]-value)>1e-14:
                raise StudioError('err.displacement_conflict',400)
            known[dof] = value
    fixed = np.array(sorted(known),int); values = np.array([known[i] for i in fixed])
    free = np.setdiff1d(np.arange(ndof),fixed)
    near_null = rigid[free].toarray() if len(free)>fem.DIRECT_LIMIT else None
    dead = fem.surface_forces(nodes,tractions).ravel()
    if nodal_forces is not None:
        dead += np.asarray(nodal_forces).ravel()
    if acceleration is not None:
        dead += fem.body_forces(nodes,tets,rho,acceleration).ravel()
    spring = np.zeros(ndof) if springs is None else np.asarray(springs).ravel()
    u = np.zeros(ndof)
    initial_system = mech.assemble(u)
    K0,initial_internal = initial_system[:2]
    del initial_system
    stiffness = max(float(K0.diagonal().mean()),1.)*al_factor
    contact = Constraints(contact_pairs,ndof,stiffness)
    contact.blocked = (np.asarray(contact.B[:,free].multiply(contact.B[:,free]).sum(1)).ravel()<1e-24).reshape(-1,3)
    lam = np.zeros(contact.B.shape[0])
    snapshots,curve,histories = [],[],[]
    current,failed = 0.,False
    count = 10 if steps == 'auto' else int(steps)
    minimum_increment = 1/count/2**8
    schedule = list(path) if path is not None else [1.]
    last = None; attempts = 0; increment = 1/count; target_index = 0
    iterations = 0
    force_reference = max(np.linalg.norm(dead),np.linalg.norm(initial_internal))
    while target_index < len(schedule):
        target = float(schedule[target_index])
        if abs(target-current)<1e-12:
            target_index += 1; increment = 1/count
            continue
        fraction = current+np.sign(target-current)*min(increment,abs(target-current))
        trial_u,trial_lam = u.copy(),lam.copy()
        trial_u[fixed] = values*fraction
        if len(snapshots)>=2 and not prescribed and not contact.count:
            previous = curve[-1]['load_fraction']-curve[-2]['load_fraction']
            if previous*(fraction-current)>0:
                trial_u += (u-snapshots[-2]['u'].ravel())*((fraction-current)/previous)
                trial_u[fixed] = values*fraction
        if prescribed and not contact.count:
            # Extend a face displacement into the free mesh before evaluating trial plasticity.
            # A jump confined to the last element otherwise looks like a spurious plastic hinge.
            trial_u[free] += linear_solve(K0[free][:,free],-K0[free][:,fixed]@(values*(fraction-current)),near_null=near_null)
            force_reference = max(force_reference,np.linalg.norm(K0@trial_u))
        if contact.count and not snapshots:
            # At zero pressure the Coulomb disk has zero radius. Seed its normal multiplier so the
            # first tangent can enter stick, instead of sending a softly supported body far away.
            load_scale = max(np.linalg.norm(dead.reshape(-1,3).sum(0))*abs(fraction),1e-12)
            trial_lam.reshape(-1,3)[:,0] = load_scale*contact.area/max(contact.area.sum(),1e-30)
        residual_history = []; converged = False; du_relative = np.inf
        for it in range(max_iterations):
            iterations += 1
            progress('job.nonlinear',.1+.75*min(1.,(len(curve)+1)/max(count,1)),
                     {'step':len(curve)+1,'steps':max(count,len(curve)+1),'iteration':it+1,'fraction':fraction,
                      'residual':residual_history[-1] if residual_history else None,
                      'increment':du_relative if np.isfinite(du_relative) else None})
            try:
                K,internal,sg,ep,eq,strain = mech.assemble(trial_u,fraction)
                external = dead*fraction
                if np.any(spring):
                    K = K+sp.diags(spring)
                internal = internal+spring*trial_u
                if follower is not None:
                    fp,Kp = follower(trial_u.reshape(-1,3))
                    external += fraction*fp.ravel(); K -= fraction*Kp
                residual = internal-external-contact.G@trial_lam
                rc,Cu,Cl,*_ = contact.equations(trial_u,trial_lam,fraction)
                scale = max(np.linalg.norm(external),np.linalg.norm(internal[fixed]),np.linalg.norm(contact.G@trial_lam),force_reference,1e-20)
                relative = float(np.linalg.norm(residual[free])/scale)
                contact_relative = float(np.max(np.abs(rc))*stiffness/max(np.max(np.abs(trial_lam)),scale*1e-10)) if len(rc) else 0.
                residual_history.append(relative)
                if relative < 1e-6 and contact_relative < 1e-7 and du_relative < 1e-8:
                    converged = True
                    break
                if not np.isfinite(relative) or relative > 1e10:
                    break
                if not contact.count and len(residual_history)>=8 and relative>1e-5 and min(residual_history[-4:])>.98*min(residual_history[-8:-4]):
                    break
                A = K[free][:,free]
                rhs = -residual[free]
                if len(rc):
                    # Scale multipliers to displacement units for conditioning (Pa vs metres).
                    A = sp.bmat([[A,-contact.G[free]*stiffness],[Cu[:,free]*stiffness,Cl*stiffness**2]],format='csr')
                    rhs = np.r_[rhs,-rc*stiffness]
                update = linear_solve(A,rhs,bool(len(rc)),len(free),near_null)
                del A
                du = np.zeros(ndof); du[free] = update[:len(free)]
                dl = update[len(free):]*stiffness
                # Backtrack only to keep the deformation map valid. Plastic state remains uncommitted.
                factor = 1.
                if large:
                    for _ in range(10):
                        candidate = (trial_u+factor*du)[mech.dofs].reshape(-1,10,3)
                        F = np.eye(3)+np.einsum('eai,egJa->egiJ',candidate,mech.grad)
                        if np.linalg.det(F).min() > .02:
                            break
                        factor *= .5
                if len(rc) or any(p.get('model') == 'elastoplastic' for _,p in groups):
                    merit = np.linalg.norm(np.r_[residual[free],rc*stiffness])
                    for _ in range(12):
                        cu = trial_u+factor*du; cl = trial_lam+factor*dl
                        cr = contact.equations(cu,cl,fraction)[0]
                        if mech.linear_system is not None:
                            ci = mech.linear_system[0]@cu-mech.linear_system[1]*fraction+spring*cu
                        else:
                            ci = mech.assemble(cu,fraction,tangent=False)[1]+spring*cu
                        ce = external if follower is None else dead*fraction+fraction*follower(cu.reshape(-1,3))[0]
                        candidate = ci-ce-contact.G@cl
                        new_merit = np.linalg.norm(np.r_[candidate[free],cr*stiffness])
                        if new_merit <= merit*(1-1e-4*factor) or new_merit<1e-10*scale:
                            break
                        factor *= .5
                trial_u += factor*du; trial_lam += factor*dl
                du_relative = float(np.linalg.norm(factor*du)/max(np.linalg.norm(trial_u),np.ptp(nodes,axis=0).max()*1e-12))
                if np.linalg.norm(trial_u)>1e4*max(np.ptp(nodes,axis=0).max(),1e-12):
                    break
            except (RuntimeError,ValueError,np.linalg.LinAlgError,spla.MatrixRankWarning):
                break
        if not converged:
            if contact_pairs:
                # Rank of the active support constraints on each body's exact rigid modes.
                _,Cu,_,*_=contact.equations(trial_u,trial_lam,fraction)
                spring_dofs = np.flatnonzero(spring)
                held = sp.vstack([rigid[fixed],rigid[spring_dofs],Cu@rigid]).toarray()
                norms = np.linalg.norm(held,axis=0); held /= np.maximum(norms,1e-30)
                if np.linalg.matrix_rank(held,tol=1e-8)<held.shape[1]:
                    null = np.linalg.svd(held,full_matrices=False)[2][-1]/np.maximum(norms,1e-30)
                    motion = (rigid@null).reshape(-1,3)
                    candidates = [(float(np.linalg.norm(motion[r[side]])),r['bodies'][i]) for r in contact_pairs for i,side in enumerate(('master','slave'))]
                    body = max(candidates)[1]
                    raise StudioError('err.contact_unstable',400,body='b'+str(body))
            attempts += 1
            if attempts > 8 or increment/2 < minimum_increment:
                failed = True
                break
            increment *= .5
            continue
        attempts = 0
        u,lam,current = trial_u,trial_lam,fraction
        mech.ep,mech.peeq = ep,eq
        sn = fem.gauss_to_nodes(tets,sg,n)
        fields = {'u':u.reshape(-1,3).copy(),'s':sn,'vm':von_mises(sn),
                  'peeq':np.maximum(fem.gauss_to_nodes(tets,eq,n),0)}
        cf,interfaces,comp = contact.fields(u,lam,fraction)
        contact.commit(u,lam,fraction)
        if contact_pairs:
            fields.update(cf)
        reaction = np.zeros(ndof); reaction[fixed] = residual[fixed]
        # Springs are external supports. Their reactions belong in balance as well.
        support_reaction = reaction-spring*u
        applied = external.reshape(-1,3).sum(0); react = support_reaction.reshape(-1,3).sum(0)
        am = np.cross(nodes+u.reshape(-1,3) if large else nodes,external.reshape(-1,3)).sum(0)
        rm = np.cross(nodes+u.reshape(-1,3) if large else nodes,support_reaction.reshape(-1,3)).sum(0)
        force_scale = max(np.linalg.norm(np.abs(external).reshape(-1,3).sum(0)),np.linalg.norm(support_reaction),force_reference,1e-20)
        imbalance = max(float(np.linalg.norm(applied+react)/force_scale),float(np.linalg.norm(am+rm)/max(force_scale*np.ptp(nodes,axis=0).max(),1e-20)))
        fields['reaction'] = reaction.reshape(-1,3)
        snapshots.append(fields); histories.append(residual_history)
        row = {'step':len(snapshots),'load_fraction':current,'max_disp_m':float(np.linalg.norm(fields['u'],axis=1).max()),
               'face_disp_m':np.mean(fields['u'][face_nodes],axis=0).tolist() if len(face_nodes) else [0.,0.,0.],
               'iterations':len(residual_history),'residual':relative,'increment':du_relative}
        curve.append(row)
        last = {**fields,'applied':applied,'reaction':react,'applied_moment':am,'reaction_moment':rm,
                'nodal_reaction':reaction.reshape(-1,3),'forces':external.reshape(-1,3),'imbalance':imbalance,
                'volume':float(mech.w.sum()),'ndof':ndof,'nfree':len(free),'interfaces':interfaces,
                'complementarity':comp,'max_strain':strain}
        growth = 1.5 if len(residual_history)<=6 else .75 if len(residual_history)>15 else 1.
        increment = max(minimum_increment,min(increment*growth,1/count*(2 if steps == 'auto' else 1)))
    if last is None:
        raise StudioError('err.nonlinear_diverged',400,fraction=0,residual_history=residual_history)
    return {**last,'steps':snapshots,'curve':curve,'residual_history':histories,'iterations':iterations,
            'converged':not failed and last['complementarity']<1e-6 and last['imbalance']<5e-3,
            'error':{'key':'err.nonlinear_diverged','fraction':current} if failed else None}
