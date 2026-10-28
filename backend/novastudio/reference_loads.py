"""One load-coverage guard for closed-form template comparisons."""
from . import templates
from .i18n import t


def unsupported_loads(case, modeled=()):
    physics = case.get('physics', {})
    active = {key for key in ('gravity', 'rotation') if physics.get(key, {}).get('enabled')}
    thermal = physics.get('thermal_load', {})
    if (thermal if isinstance(thermal, str) else thermal.get('mode', 'none')) != 'none':
        active.add('thermal')
    extra = sorted(active-set(modeled))
    # An allow-list of the formula's face roles also catches future load roles.
    pattern = templates.get(case['template'])['case'].get('boundaries', {})
    extra += [f"{face}: {b.get('role')}" for face, b in case['boundaries'].items()
              if b.get('role') != pattern.get(face, {}).get('role')]
    if extra:
        load = ', '.join(extra)
        return {'applicable': False, 'why': t('verify.unmodeled_load', 'en', load=load),
                'why_key': 'verify.unmodeled_load', 'why_args': {'load': load}}
    return None
