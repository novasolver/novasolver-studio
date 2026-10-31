"""Portable result artifacts. XML/CSV/HTML need no additional runtime package."""
from __future__ import annotations

import base64
import csv
from datetime import datetime
from html import escape
import json
import os
import secrets
import xml.etree.ElementTree as ET

import numpy as np

from . import __version__, results
from .i18n import t
from .store import StudioError, case_dir


def nodal_fields(data, n):
    out = {}
    for name in data.files:
        a = data[name]
        if name in ('phi','mode_shapes'):
            prefix = 'mode' if name == 'mode_shapes' else 'phi'
            out.update({f'{prefix}_{i+1}':v for i,v in enumerate(a)})
        elif a.ndim in (1,2) and len(a) == n:
            out[name] = a
    return out


def export(case, format, lang):
    if format not in ('vtu','csv','report'):
        raise StudioError('err.path',400,path='format='+format)
    jd, raw = results.load(case['case_id'])
    if not (jd/'mesh.npz').is_file():
        raise StudioError('err.path',400,path='export requires a tetrahedral result mesh')
    with np.load(jd/'mesh.npz') as mesh, np.load(jd/'results.npz') as data:
        nodes, tets = mesh['nodes'],mesh['tets']
        fields = nodal_fields(data,len(nodes))
        folder = case_dir(case['case_id'])/'exports'
        folder.mkdir(exist_ok=True)
        target = folder/(jd.name + ('.html' if format == 'report' else '.'+format))
        path = target.with_suffix(target.suffix+'.'+secrets.token_hex(4)+'.tmp')
        if format == 'vtu':
            if raw.get('curve'):
                root = ET.Element('VTKFile',type='Collection',version='0.1',byte_order='LittleEndian')
                collection = ET.SubElement(root,'Collection')
                for i,row in enumerate(raw['curve']):
                    filename = f'{jd.name}_step_{i+1:04d}.vtu'
                    step_fields = {k[5:]:data[k][i] for k in data.files if k.startswith('step_')}
                    write_vtu(folder/filename,nodes,tets,step_fields)
                    ET.SubElement(collection,'DataSet',timestep=str(i+1),group='',part='0',file=filename)
                target = target.with_suffix('.pvd')
                ET.ElementTree(root).write(path,encoding='utf-8',xml_declaration=True)
                os.replace(path,target)
                return target
            from .fem_tet10 import canonical_tets
            tets = canonical_tets(nodes,tets) if tets.shape[1] == 10 else tets
            root = ET.Element('VTKFile',type='UnstructuredGrid',version='0.1',byte_order='LittleEndian')
            grid = ET.SubElement(root,'UnstructuredGrid')
            piece = ET.SubElement(grid,'Piece',NumberOfPoints=str(len(nodes)),NumberOfCells=str(len(tets)))
            def array(parent, name, values, dtype='Float64'):
                a = np.asarray(values)
                attrs = {'type':dtype,'format':'ascii'}
                if name:
                    attrs['Name'] = name
                if a.ndim == 2:
                    attrs['NumberOfComponents'] = str(a.shape[1])
                el = ET.SubElement(parent,'DataArray',attrs)
                el.text = ' '.join(str(int(v)) if dtype.startswith('Int') or dtype.startswith('UInt') else f'{v:.16g}' for v in a.ravel())
            array(ET.SubElement(piece,'Points'),None,nodes)
            cells = ET.SubElement(piece,'Cells')
            array(cells,'connectivity',tets.ravel(),'Int64')
            array(cells,'offsets',np.arange(1,len(tets)+1)*tets.shape[1],'Int64')
            array(cells,'types',np.full(len(tets),24 if tets.shape[1] == 10 else 10),'UInt8')
            point = ET.SubElement(piece,'PointData')
            for name,a in fields.items():
                array(point,name,a)
            ET.SubElement(piece,'CellData')
            ET.ElementTree(root).write(path,encoding='utf-8',xml_declaration=True)
        elif format == 'csv':
            with path.open('w',encoding='utf-8',newline='') as fh:
                writer = csv.writer(fh)
                if raw.get('curve'):
                    writer.writerow(['step','load_fraction','max_disp_m','face_ux_m','face_uy_m','face_uz_m'])
                    writer.writerows([r['step'],r['load_fraction'],r['max_disp_m'],*r['face_disp_m']] for r in raw['curve'])
                elif raw['kind'] == 'modal':
                    writer.writerow(['mode','frequency_hz','effective_mass_x','effective_mass_y','effective_mass_z'])
                    for m in raw['modes']:
                        writer.writerow([m['mode'],m['frequency_hz'],*m['effective_mass']])
                elif raw['kind'] == 'buckling':
                    writer.writerow(['mode','load_factor','critical_load_n'])
                    for m in raw['modes']:
                        writer.writerow([m['mode'],m['load_factor'],m['critical_load_n']])
                else:
                    header = ['node','x_m','y_m','z_m']
                    arrays = [nodes]
                    for name,a in fields.items():
                        a = a.reshape(len(nodes),-1)
                        header += [name] if a.shape[1] == 1 else [f'{name}_{i+1}' for i in range(a.shape[1])]
                        arrays.append(a)
                    values = np.column_stack(arrays)
                    writer.writerow(header)
                    writer.writerows([i+1,*row] for i,row in enumerate(values))
        else:
            path.write_text(report(case,jd,raw,lang),encoding='utf-8')
        os.replace(path,target)
    return target


def write_vtu(path,nodes,tets,fields):
    from .fem_tet10 import canonical_tets
    tets = canonical_tets(nodes,tets)
    root = ET.Element('VTKFile',type='UnstructuredGrid',version='0.1',byte_order='LittleEndian')
    piece = ET.SubElement(ET.SubElement(root,'UnstructuredGrid'),'Piece',NumberOfPoints=str(len(nodes)),NumberOfCells=str(len(tets)))
    def array(parent,name,data,dtype='Float64'):
        data = np.asarray(data)
        attrs = {'type':dtype,'format':'ascii'}
        if name: attrs['Name'] = name
        if data.ndim>1: attrs['NumberOfComponents'] = str(data.shape[1])
        ET.SubElement(parent,'DataArray',attrs).text = ' '.join(str(v) for v in data.ravel())
    array(ET.SubElement(piece,'Points'),None,nodes)
    cells = ET.SubElement(piece,'Cells')
    array(cells,'connectivity',tets.ravel(),'Int64')
    array(cells,'offsets',np.arange(1,len(tets)+1)*10,'Int64')
    array(cells,'types',np.full(len(tets),24),'UInt8')
    point = ET.SubElement(piece,'PointData')
    for name,values in fields.items():
        array(point,name,values)
    ET.SubElement(piece,'CellData')
    temporary = path.with_suffix('.tmp')
    ET.ElementTree(root).write(temporary,encoding='utf-8',xml_declaration=True)
    os.replace(temporary,path)


UNIT_LABEL = {'degC': '°C', 'W/m2': 'W/m²', 'W/m2K': 'W/(m²·K)', 'W/mK': 'W/(m·K)', 'kg/m3': 'kg/m³', 'm2/s': 'm²/s',
              'mm2': 'mm²', 'm/s2': 'm/s²', 'A/m2': 'A/m²', 'C/m2': 'C/m²', 'Nm': 'N·m', 'N-m': 'N·m', 'ohm': 'Ω',
              'mohm': 'mΩ', '-': ''}


def _num(v, digits=4) -> str:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return str(v)
    if float(v).is_integer() and abs(v) >= 1000:
        return f'{int(v):,}'                                  # counts: "55,325", not "5.532e+04"
    if v == 0 or 1e-3 <= abs(v) < 1e6:
        return f'{v:.{digits}g}'
    return f'{v:.{digits - 1}e}'


def _si(v, unit: str, digits=6) -> str:
    """A value in SI with its unit, scaled to a readable prefix for stresses (2.46e8 Pa -> 246 MPa)."""
    if unit == 'Pa' and isinstance(v, (int, float)) and abs(v) >= 1e3:
        for f, u in ((1e9, 'GPa'), (1e6, 'MPa'), (1e3, 'kPa')):
            if abs(v) >= f:
                return f'{v / f:.{digits}g} {u}'
    u = UNIT_LABEL.get(unit, unit)
    return _num(v, digits) + (' ' + u if u else '')


def _quantity(v) -> str:
    """{'value': 500, 'unit': 'N'} -> '500 N'; lists and plain values as they are."""
    if isinstance(v, dict) and 'value' in v:
        u = UNIT_LABEL.get(v.get('unit', ''), v.get('unit', ''))
        return (_num(v['value']) + (' ' + u if u else '')).strip()
    if isinstance(v, list):
        return '[' + ', '.join(_quantity(x) for x in v) + ']'
    if isinstance(v, str) and len(v) <= 3 and v[:1] in '+-':          # directions such as "-z"
        return v.replace('-', '−').upper()
    return str(v)


def _label(prefix: str, key: str, lang: str) -> str:
    s = t(f'{prefix}.{key}', lang)
    return key if s == f'{prefix}.{key}' else s


def report(case,jd,raw,lang):
    """One self-contained HTML page a person can read, file and print to PDF: what was set up, what came out, and
    how far the answer has been checked. No paths of this PC and no personal names."""
    from .commands import face_label
    from .templates import get
    request = jd/'request.json'
    if request.is_file():
        case = json.loads(request.read_text(encoding='utf-8'))['case']
    pl = results.payload(case,lang,jd.name)
    def h(s):
        return escape(str(s),quote=True)
    def image(png, alt):
        return '<figure><img alt="'+h(alt)+'" src="data:image/png;base64,'+base64.b64encode(png).decode()+'"></figure>'
    def heading(key):
        return '<h2>'+h(t('export.'+key,lang))+'</h2>'
    def table(head, rows, num_cols=()):
        out = '<table><thead><tr>'+''.join('<th'+(' class="n"' if i in num_cols else '')+'>'+h(c)+'</th>'
                                          for i, c in enumerate(head))+'</tr></thead><tbody>'
        for row in rows:
            out += '<tr>'+''.join('<td'+(' class="n"' if i in num_cols else '')+'>'+h(v)+'</td>' for i, v in enumerate(row))+'</tr>'
        return out+'</tbody></table>'
    def values(b):
        parts = []
        for k, v in b.items():
            if k in ('role', 'thermal'):
                continue
            parts.append(_label('field', k, lang)+' '+_quantity(v))
        th = b.get('thermal')
        if th:
            sub = [_label('field', k, lang)+' '+_quantity(v) for k, v in th.items() if k != 'role']
            parts.append(t('export.thermal', lang)+': '+_label('role', th.get('role', ''), lang)+(' ('+', '.join(sub)+')' if sub else ''))
        return ', '.join(parts) or '—'
    tp = get(case['template'])
    title = case['title'].get(lang,case['title'].get('en','NovaSolver Studio'))
    html = '<!doctype html><html lang="'+lang+'"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>'+h(title)+'</title>'
    html += ('<style>body{font:14px/1.6 system-ui,-apple-system,"Segoe UI","Yu Gothic UI","Microsoft YaHei",sans-serif;'
             'max-width:960px;margin:32px auto;padding:0 24px;color:#20252a}h1{font-size:22px;margin:0 0 4px}'
             'h2{font-size:17px;margin:28px 0 8px;padding-bottom:4px;border-bottom:1px solid #c9ccd1}'
             'table{border-collapse:collapse;width:100%;margin:6px 0}th,td{border-bottom:1px solid #e1e3e6;padding:5px 8px;'
             'text-align:left;vertical-align:top;overflow-wrap:anywhere}th{font-weight:600;color:#4a5058}'
             'td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.meta{color:#5b626b;margin:0 0 16px}'
             '.ok{color:#15803d;font-weight:600}.ng{color:#b91c1c;font-weight:600}figure{margin:12px 0}'
             'img{max-width:100%;max-height:460px;border:1px solid #e1e3e6}footer{margin-top:32px;color:#5b626b;font-size:12px}'
             '@media print{body{margin:0}h2{break-after:avoid}img,table{break-inside:avoid}}</style><body>')
    html += ('<h1>'+h(title)+'</h1><p class="meta">'+h(t('export.title',lang))+' · '+h(t('export.date',lang))+' '
             +datetime.now().strftime('%Y-%m-%d %H:%M')+' · NovaSolver Studio '+h(__version__)+'</p>')
    # 1. setup
    html += heading('physics')
    phys = case.get('physics', {})
    # "analysis" (e.g. modal) overrides the physics kind (linear-static) of a structural case: name only one
    kind = phys.get('analysis') or phys.get('kind')
    rows = [(t('export.analysis', lang), _label('physics', tp['physics'], lang)+(' / '+_label('analysis', kind, lang) if kind else ''))]
    for k in ('modes', 'nonlinear', 'thermal_load', 'gravity', 'rotation', 'joule_heating'):
        if k in phys and phys[k] not in (None, False, {}):
            v = phys[k]
            if isinstance(v, dict):
                if v.get('enabled') is False:
                    continue
                # {"mode": "uniform", "temperature": 120 degC} -> "uniform temperature, 120 °C"
                v = ', '.join((_label('thermal_load', vv, lang) if kk == 'mode' else _label('field', kk, lang)+' '+_quantity(vv))
                              for kk, vv in v.items() if kk != 'enabled')
            rows.append((_label('field', k, lang), _quantity(v)))
    html += table((t('export.item', lang), t('export.value', lang)), rows)
    # the faces picture of render_view(quantity="faces"), from the run snapshot even if the case was edited since;
    # front and back, because a support or load is often on a face the first view hides
    html += ('<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">'
             + image(results.render_faces(case,lang)[0], t('export.boundaries', lang))
             + image(results.render_faces(case,lang,view='iso_back')[0], t('export.boundaries', lang)) + '</div>')
    html += heading('boundaries')+table((t('export.face', lang), t('export.role', lang), t('export.values', lang)),
        [(face_label(tp,f,lang,case), _label('role', b['role'], lang), values(b)) for f,b in case['boundaries'].items()])
    if raw.get('interfaces'):
        from .contact import settings
        html += heading('contacts')+table((t('export.face',lang),t('export.role',lang),'μ',t('field.offset',lang),t('export.force',lang)),
            [(face_label(tp,f,lang,case),t('contact.'+settings(case,f)['type'],lang),settings(case,f)['mu'],
              _quantity(settings(case,f)['offset']),_si(v['normal_force_n'],'N')) for f,v in raw['interfaces'].items()])
    html += heading('materials')
    # only the properties this analysis uses (a structural case does not need permittivity); "nu" is Poisson's
    # ratio for a solid and kinematic viscosity for a fluid
    used = {'structural': ('E', 'nu', 'rho', 'sy', 'H', 'model', 'alpha', 'k'), 'thermal': ('k',), 'electric': ('eps_r', 'sigma', 'k'),
            'flow': ('nu', 'rho'), 'cfd': ('nu', 'rho'), 'external': ('nu', 'rho')}.get(tp['physics'])
    solid_label = {'nu': 'param.poisson', 'sy': 'param.sy'}
    for name, mat in case['materials'].items():
        props = [(t(solid_label[k], lang) if name == 'solid' and k in solid_label else _label('param', k, lang), _quantity(v))
                 for k, v in mat.items() if k != 'preset' and (used is None or name != 'solid' or k in used)]
        html += '<p><b>'+h(_label('material', mat.get('preset', name), lang))+'</b></p>'+table((t('export.property', lang), t('export.value', lang)), props, (1,))
    if case.get('body_materials'):
        html += table((t('export.body', lang), t('export.materials', lang), t('export.values', lang)),
                      [(k, _label('material', v, lang), ', '.join(_label('param', kk, lang)+' '+_quantity(vv)
                        for kk, vv in case.get('body_props', {}).get(k, {}).items()) or '—') for k, v in case['body_materials'].items()])
    m = raw['metrics']
    html += heading('mesh')+table((t('export.item', lang), t('export.value', lang)),
        [(t('card.nodes',lang), f"{m['nodes']:,}"), (t('card.elements',lang), f"{m['elements']:,}"),
         (t('export.element', lang), t('export.tet10', lang))], (1,))
    # 2. results
    html += heading('results')+table((t('export.item', lang), t('export.value', lang)),
        [(c['label'], _num(c['value'])+(' '+UNIT_LABEL.get(c['unit'], c['unit']) if UNIT_LABEL.get(c['unit'], c['unit']) else '')) for c in pl['cards']], (1,))
    html += image(results.render_png(case,'',lang,jd.name)[0], t('export.results', lang))
    if raw.get('curve'):
        import io
        import matplotlib.pyplot as plt
        fig,ax = plt.subplots(figsize=(7,3.5))
        ax.plot([v['max_disp_m']*1000 for v in raw['curve']],[v['load_fraction'] for v in raw['curve']])
        ax.set_xlabel(t('qty.disp',lang)+' [mm]'); ax.set_ylabel(t('field.load_fraction',lang)); ax.grid(alpha=.2)
        buf = io.BytesIO(); fig.tight_layout(); fig.savefig(buf,format='png'); plt.close(fig)
        html += heading('curve')+image(buf.getvalue(),t('export.curve',lang))
    if raw['kind'] == 'modal':
        html += table((t('export.mode', lang), 'f [Hz]', 'Mx %', 'My %', 'Mz %'),
                      [(x['mode'], _num(x['frequency_hz'], 5), *[('0' if e*100 < .05 else f'{e*100:.1f}') for e in x['effective_mass']])
                       for x in raw['modes']], (1, 2, 3, 4))
    if raw['kind'] == 'buckling':
        html += table((t('export.mode', lang), 'λ', 'P_cr [N]'),
                      [(x['mode'], _num(x['load_factor'], 5), _num(x['critical_load_n'], 5)) for x in raw['modes']], (1, 2))
    # 3. how far the answer is checked
    html += heading('verification')
    gates = pl['gates']
    html += table((t('export.gate', lang), t('export.status', lang), t('export.meaning', lang)),
        [(t('gate.'+g, lang), ('✓ ' if gates[g] else '✗ ')+t('export.yes' if gates[g] else 'export.no', lang),
          # the GUI strings start with the gate's English name ("ran：..."); the table already names it
          t('export.'+g, lang).split('：', 1)[-1].split(': ', 1)[-1])
         for g in ('ran','converged','verified')])
    v = pl.get('verification') or {}
    if v:
        rows = [(t('export.check', lang), v.get('label', '')),
                (v.get('reference_label') or t('export.reference', lang), _si(v.get('reference'), v.get('unit', ''))),
                (t('export.computed', lang), _si(v.get('computed'), v.get('unit', ''))),
                (t('export.difference', lang), f"{v.get('error_pct', 0):+.2f} %"),
                (t('export.tolerance', lang), f"±{v.get('tolerance_pct', 0):g} %"),
                (t('export.verdict', lang), t('export.pass' if v.get('pass') else 'export.fail', lang))]
        if raw.get('reference', {}).get('formula'):
            rows.append((t('export.formula', lang), raw['reference']['formula']))
        html += table((t('export.item', lang), t('export.value', lang)), rows)
    conv = raw.get('convergence')
    if conv:
        u = UNIT_LABEL.get(conv.get('unit', ''), conv.get('unit', ''))
        html += '<p>'+h(t('export.mesh_study', lang))+'</p>'+table(
            (t('export.level', lang), t('card.elements', lang), (conv.get('quantity') or '')+(' ['+u+']' if u else '')),
            [(l['size'], f"{l['elements']:,}", _num(l['value'], 6)) for l in conv.get('levels', [])], (1, 2))
        html += table((t('export.item', lang), t('export.value', lang)),
                      [('GCI', f"{conv.get('gci_pct', 0):.3g} %"), (t('export.tolerance', lang), f"{conv.get('tolerance_pct', 5):g} %"),
                       (t('export.verdict', lang), t('export.pass' if conv.get('pass') else 'export.fail', lang))])
    for w in pl.get('warnings',[]):
        html += '<p class="ng">'+h(w['message'])+'</p>'
    return html+'<footer>'+h(t('export.footer', lang))+' · novasolver.jp/studio</footer></body></html>'
