"""High-cycle fatigue from a linear static result (stress-life). The static load is the peak of a constant-amplitude
cycle between R x load and load. Per node: amplitude and mean of the signed von Mises stress, the Goodman safety
factor and the life from the S-N line through (1e3 cycles, 0.9 Su) and (Ne, Se) (Shigley's estimates).
Only for metals with Su and Se; the endurance limit is reduced by the surface factor of the finish.
"""
from __future__ import annotations

import numpy as np

# Ultimate strength and fully reversed endurance limit of a polished specimen (rotating beam), MPa; Ne the knee.
# Aluminium has no true endurance limit: Se is the strength at 5e8 cycles and the line continues past it.
METALS = {
    'steel': {'su': 400, 'se': 200, 'ne': 1e6},          # SS400 / S235: Se' = 0.5 Su
    'alloy_steel': {'su': 980, 'se': 490, 'ne': 1e6},    # SCM440 quenched and tempered
    'titanium': {'su': 950, 'se': 510, 'ne': 1e7},       # Ti-6Al-4V annealed
    'aluminium': {'su': 310, 'se': 96, 'ne': 5e8},       # 6061-T6
    'copper': {'su': 220, 'se': 76, 'ne': 1e8},          # C1100 annealed
}
# Marin surface factor ka = a Su^b (Su in MPa), Shigley Table 6-2
SURFACE = {'polished': (1.0, 0.0), 'ground': (1.58, -0.085), 'machined': (4.51, -0.265),
           'hot-rolled': (57.7, -0.718), 'as-forged': (272., -0.995)}
INFINITE = 1e10           # cycles reported for "below the endurance limit"


def settings(case):
    f = case.get('physics', {}).get('fatigue', {})
    return {'enabled': bool(f.get('enabled')), 'ratio': float(f.get('ratio', -1.0)),
            'surface': f.get('surface', 'machined'), 'cycles': float(f.get('cycles', 1e6))}


def material(case, body=None):
    """Fatigue data of the case's (or a body's) material preset, overridden by su / se given on the material."""
    from . import units
    mat = case['materials']['solid']
    preset = case.get('body_materials', {}).get(body) if body else mat.get('preset')
    base = METALS.get(preset)
    own = case.get('body_props', {}).get(body, {}) if body else mat
    su = units.to_si(own['su']) / 1e6 if own.get('su') else (base or {}).get('su')
    se = units.to_si(own['se']) / 1e6 if own.get('se') else (base or {}).get('se')
    if not su or not se:
        return None
    return {'su': su, 'se': se, 'ne': (base or {}).get('ne', 1e6), 'endurance': preset != 'aluminium'}


def evaluate(stress, case, mat):
    """stress (n,6) Pa at nodes -> safety factor and life per node, with the inputs used."""
    cfg = settings(case)
    a_, b_ = SURFACE.get(cfg['surface'], SURFACE['machined'])
    ka = min(1.0, a_ * mat['su'] ** b_)
    se = ka * mat['se'] * 1e6
    su = mat['su'] * 1e6
    s = np.asarray(stress)
    vm = np.sqrt(0.5 * ((s[:, 0] - s[:, 1]) ** 2 + (s[:, 1] - s[:, 2]) ** 2 + (s[:, 2] - s[:, 0]) ** 2)
                 + 3 * (s[:, 3] ** 2 + s[:, 4] ** 2 + s[:, 5] ** 2))
    sign = np.where(s[:, :3].sum(1) >= 0, 1.0, -1.0)   # tension-dominated (+) or compression-dominated (-) points
    R = cfg['ratio']
    amp = (1 - R) / 2 * vm
    mean = (1 + R) / 2 * vm * sign
    # Goodman for a tensile mean; a compressive mean is given no credit (conservative)
    with np.errstate(divide='ignore', invalid='ignore'):
        sf = np.where(mean > 0, 1 / (amp / se + mean / su), se / amp)
        sf = np.where(amp > 0, sf, np.inf)
        sar = np.where(mean > 0, amp / np.maximum(1 - mean / su, 1e-9), amp)   # equivalent fully reversed amplitude
        # S-N line: sar = A N^b through (1e3, 0.9 Su) and (Ne, Se)
        b = np.log10(se / (0.9 * su)) / np.log10(mat['ne'] / 1e3)
        A = 0.9 * su / 1e3 ** b
        life = np.where(sar > 0, (sar / A) ** (1 / b), INFINITE)
        if mat['endurance']:
            life = np.where(sar <= se, INFINITE, life)
        life = np.where(mean / su >= 1, 0.0, np.clip(life, 0, INFINITE))
    return {'sf': sf, 'life': life, 'se_pa': se, 'su_pa': su, 'ka': ka, 'ratio': R}
