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
                if raw['kind'] == 'modal':
                    writer.writerow(['mode','frequency_hz','effective_mass_x','effective_mass_y','effective_mass_z'])
                    for m in raw['modes']:
                        writer.writerow([m['mode'],m['frequency_hz'],*m['effective_mass']])
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


def report(case,jd,raw,lang):
    from .commands import face_label
    from .templates import get
    request = jd/'request.json'
    if request.is_file():
        case = json.loads(request.read_text(encoding='utf-8'))['case']
    pl = results.payload(case,lang,jd.name)
    def h(s):
        return escape(str(s),quote=True)
    def image(png):
        return '<img alt="NovaSolver Studio" src="data:image/png;base64,'+base64.b64encode(png).decode()+'">'
    def heading(key):
        return '<h2>'+h(t('export.'+key,lang))+'</h2>'
    def table(rows):
        return '<table>'+''.join('<tr>'+''.join('<td>'+h(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</table>'
    tp = get(case['template'])
    title = case['title'].get(lang,case['title'].get('en','NovaSolver Studio'))
    html = '<!doctype html><html lang="'+lang+'"><meta charset="utf-8"><title>'+h(title)+'</title>'
    html += '<style>body{font:14px/1.6 system-ui,sans-serif;max-width:960px;margin:32px auto;padding:0 24px;color:#20252a}h1{font-size:24px}h2{font-size:18px;margin-top:28px}table{border-collapse:collapse;width:100%}td{border-bottom:1px solid #bbb;padding:6px;text-align:left;overflow-wrap:anywhere}img{max-width:100%;max-height:480px}pre{white-space:pre-wrap}@media print{body{margin:0}h2{break-after:avoid}img,table{break-inside:avoid}}</style><body>'
    html += '<h1>'+h(title)+' — '+h(t('export.title',lang))+'</h1><p>'+h(t('export.date',lang))+': '+datetime.now().isoformat(timespec='seconds')+'</p>'
    # The render_view(quantity="faces") renderer, using the run snapshot even after the case was edited.
    html += image(results.render_faces(case,lang)[0])
    html += heading('boundaries')+table([(face_label(tp,f,lang,case),t('role.'+b['role'],lang),
        json.dumps({k:v for k,v in b.items() if k != 'role'},ensure_ascii=False)) for f,b in case['boundaries'].items()])
    html += heading('materials')+table([(k,json.dumps(v,ensure_ascii=False)) for k,v in case['materials'].items()])
    if case.get('body_materials'):
        html += table([(k,v,json.dumps(case.get('body_props',{}).get(k,{}),ensure_ascii=False)) for k,v in case['body_materials'].items()])
    html += heading('mesh')+table([(t('card.nodes',lang),raw['metrics']['nodes']),
                                  (t('card.elements',lang),raw['metrics']['elements']),('element','tet10')])
    html += heading('results')+table([(c['label'],c['value'],c['unit']) for c in pl['cards']])
    html += image(results.render_png(case,'',lang,jd.name)[0])
    if raw['kind'] == 'modal':
        html += table([('mode','Hz','Mx','My','Mz')]+[(m['mode'],m['frequency_hz'],*m['effective_mass']) for m in raw['modes']])
    html += heading('verification')+table([(key,str(pl['gates'][key]),t('export.'+key,lang)) for key in ('ran','converged','verified')])
    html += '<p>reference: '+h(json.dumps(pl.get('verification'),ensure_ascii=False))+'</p>'
    html += '<p>'+h(raw.get('reference',{}).get('formula','GCI'))+'</p>'
    if raw.get('convergence'):
        html += '<p>GCI: '+h(json.dumps(raw['convergence'],ensure_ascii=False))+'</p>'
    for w in pl.get('warnings',[]):
        html += '<p>'+h(w['message'])+'</p>'
    return html+'<footer>NovaSolver Studio '+h(__version__)+'</footer></body></html>'
