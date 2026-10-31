import { change, detectContacts, selectFace, setState, useStore, useT } from '../state/store';
import { Button } from './ui/Button';
import { NumberInput } from './ui/Input';
import { Select } from './ui/Select';
import { Field, SectionLabel } from './ui/misc';
import type { Quantity } from '../api/types';

export function VectorInput({ value, label, unit = 'mm', onCommit }: { value: number[]; label: string; unit?: string; onCommit: (v: number[]) => void }) {
  // one row per axis: three inputs side by side in the 300 px panel were 35 px wide and showed "200" as "20"
  return <div className="flex flex-col gap-1">{['X','Y','Z'].map((axis,i) => <div key={axis} className="flex items-center gap-2">
    <span className="w-3 shrink-0 text-label text-fg-3">{axis}</span>
    <div className="min-w-0 flex-1"><NumberInput ariaLabel={`${label} ${axis}`} value={value[i] ?? 0} unit={unit}
      onCommit={v => { const next=[...value]; next[i]=v; onCommit(next); }} /></div></div>)}</div>;
}

function Temperature({ path, label, value }: { path: string; label: string; value?: Quantity }) {
  return <Field label={label}><NumberInput ariaLabel={label} value={Number(value?.value ?? 20)} unit={value?.unit ?? 'degC'} units={['degC','K']}
    onCommit={(v,u) => change(path,{value:v,unit:u ?? value?.unit ?? 'degC'})} /></Field>;
}

export function StructuralSettings() {
  const t = useT();
  const p = useStore(s => s.payload);
  if (p?.ui.physics !== 'structural') return null;
  const physics = p.case.physics;
  const modal = physics?.analysis === 'modal';
  const buckling = physics?.analysis === 'buckling';
  const nonlinear = physics?.analysis === 'nonlinear';
  const thermal = physics?.thermal_load?.mode ?? 'none';
  return <>
    <section className="px-4 pt-6"><SectionLabel>{t('struct.analysis')}</SectionLabel>
      <Select value={nonlinear ? 'nonlinear':modal ? 'modal':buckling ? 'buckling':'static'} ariaLabel={t('struct.analysis')}
        options={['static','modal','buckling','nonlinear'].map(v => ({value:v,label:t('struct.'+v)}))} onChange={v => change('physics.analysis',v)} />
      {buckling && <div className="mt-4"><Field label={t('struct.modes')}><NumberInput ariaLabel={t('struct.modes')} value={physics?.modes ?? 4} min={1} max={20}
        onCommit={v => change('physics.modes',v)} /></Field><p className="prose-ui mt-2 text-label text-fg-2">{t('struct.bucklingNote')}</p></div>}
      {nonlinear && <div className="mt-4 flex flex-col gap-4">
        <label className="flex h-8 items-center gap-2 text-body text-fg"><input type="checkbox" checked={physics?.nonlinear?.large_deformation !== false}
          onChange={e => change('physics.nonlinear.large_deformation',e.target.checked)} />{t('struct.large')}</label>
        <Field label={t('struct.steps')}><Select value={physics?.nonlinear?.steps === 'auto' || !physics?.nonlinear?.steps ? 'auto':'number'}
          ariaLabel={t('struct.steps')} options={['auto','number'].map(v => ({value:v,label:t('struct.'+v)}))}
          onChange={v => change('physics.nonlinear.steps',v === 'auto' ? 'auto':10)} />
          {typeof physics?.nonlinear?.steps === 'number' && <NumberInput ariaLabel={t('struct.steps')} value={physics.nonlinear.steps} min={1} max={1000}
            onCommit={v => change('physics.nonlinear.steps',v)} />}</Field>
        <Field label={t('struct.maxIterations')}><NumberInput ariaLabel={t('struct.maxIterations')} value={physics?.nonlinear?.max_iterations ?? 25} min={2} max={100}
          onCommit={v => change('physics.nonlinear.max_iterations',v)} /></Field>
        <Field label={t('struct.trackedFace')}><Select ariaLabel={t('struct.trackedFace')} value={physics?.nonlinear?.face ?? (p.ui.faces.some(f => f.key === 'x1') ? 'x1':p.ui.faces[0]?.key)}
          options={p.ui.faces.map(f => ({value:f.key,label:f.label}))} onChange={v => change('physics.nonlinear.face',v)} /></Field>
        <p className="prose-ui text-label text-fg-2">{t('struct.follower')}</p>
      </div>}
      {modal && <div className="mt-4"><Field label={t('struct.modes')}><NumberInput ariaLabel={t('struct.modes')} value={physics?.modes ?? 6} min={1} max={30}
        onCommit={v => change('physics.modes',v)} /></Field><p className="prose-ui mt-2 text-label text-fg-2">{t('struct.loadsIgnored')}</p></div>}
    </section>
    {nonlinear && <section className="px-4 pt-6"><SectionLabel>{t('struct.models')}</SectionLabel>
      {p.case.body_materials ? Object.keys(p.case.body_materials).map(b => <MaterialModel key={b} body={b} />):<MaterialModel />}
    </section>}
    {!modal && !buckling && !nonlinear && <section className="px-4 pt-6"><SectionLabel>{t('fatigue.title')}</SectionLabel>
      <label className="flex h-8 items-center gap-2 text-body text-fg"><input type="checkbox" checked={!!physics?.fatigue?.enabled}
        onChange={e => change('physics.fatigue.enabled',e.target.checked)} />{t('fatigue.enable')}</label>
      {physics?.fatigue?.enabled && <div className="mt-3 flex flex-col gap-4">
        <Field label={t('fatigue.ratio')}><NumberInput ariaLabel={t('fatigue.ratio')} value={physics.fatigue.ratio ?? -1} min={-1} max={0.99}
          onCommit={v => change('physics.fatigue.ratio',v)} /></Field>
        <Field label={t('fatigue.surface')}><Select ariaLabel={t('fatigue.surface')} value={physics.fatigue.surface ?? 'machined'}
          options={['polished','ground','machined','hot-rolled','as-forged'].map(v => ({value:v,label:t('fatigue.surface.'+v)}))}
          onChange={v => change('physics.fatigue.surface',v)} /></Field>
        <p className="prose-ui text-label text-fg-2">{t('fatigue.note')}</p>
      </div>}
    </section>}
    {!modal && !buckling && <>
      <section className="px-4 pt-6"><SectionLabel>{t('struct.thermal')}</SectionLabel>
        <Select value={thermal} ariaLabel={t('struct.thermal')} options={['none','uniform','solve'].map(v => ({value:v,label:t('struct.thermal.'+v)}))}
          onChange={v => change('physics.thermal_load.mode',v)} />
        {thermal !== 'none' && <div className="mt-4 flex flex-col gap-4">
          <Temperature path="physics.T_ref" value={physics?.T_ref} label={t('struct.tRef')} />
          {thermal === 'uniform' && <Temperature path="physics.thermal_load.temperature" value={physics?.thermal_load?.temperature ?? {value:120,unit:'degC'}} label={t('struct.temperature')} />}
          {thermal === 'solve' && <p className="prose-ui text-label text-fg-2">{t('struct.thermalFaces')}</p>}
        </div>}
      </section>
      <section className="px-4 pt-6"><SectionLabel>{t('struct.bodyLoads')}</SectionLabel>
        <label className="flex h-8 items-center gap-2 text-body text-fg"><input type="checkbox" checked={!!physics?.gravity?.enabled}
          onChange={e => change('physics.gravity.enabled',e.target.checked)} />{t('struct.gravity')}</label>
        {physics?.gravity?.enabled && <div className="mt-3 flex flex-col gap-4">
          <Field label={t('struct.acceleration')}><NumberInput ariaLabel={t('struct.acceleration')} value={Number(physics.gravity.g?.value ?? 9.81)} unit="m/s2" min={0}
            onCommit={v => change('physics.gravity.g',{value:v,unit:'m/s2'})} /></Field>
          <Field label={t('struct.direction')}><Select ariaLabel={t('struct.direction')} value={physics.gravity.direction ?? '-z'}
            options={['-x','+x','-y','+y','-z','+z'].map(v => ({value:v,label:v.toUpperCase()}))} onChange={v => change('physics.gravity.direction',v)} /></Field>
        </div>}
        <label className="mt-3 flex h-8 items-center gap-2 text-body text-fg"><input type="checkbox" checked={!!physics?.rotation?.enabled}
          onChange={e => change('physics.rotation.enabled',e.target.checked)} />{t('struct.rotation')}</label>
        {physics?.rotation?.enabled && <div className="mt-3 flex flex-col gap-4">
          <Field label={t('struct.rpm')}><NumberInput ariaLabel={t('struct.rpm')} value={physics.rotation.rpm ?? 0} unit="rpm" min={0}
            onCommit={v => change('physics.rotation.rpm',v)} /></Field>
          <Field label={t('struct.axis')}><Select value={physics.rotation.axis ?? 'z'} ariaLabel={t('struct.axis')}
            options={['x','y','z'].map(v => ({value:v,label:v.toUpperCase()}))} onChange={v => change('physics.rotation.axis',v)} /></Field>
          <Field label={t('struct.axisPoint')}><VectorInput value={physics.rotation.axis_point ?? [0,0,0]} label={t('struct.axisPoint')}
            onCommit={v => change('physics.rotation.axis_point',v)} /></Field>
        </div>}
      </section>
    </>}
  </>;
}

function MaterialModel({body}:{body?:string}) {
  const t = useT(); const p = useStore(s => s.payload)!;
  const material: Record<string,unknown> = {...p.ui.material_models?.[body ?? 'solid'],...(body ? p.case.body_props?.[body] : p.case.materials?.solid)};
  const path = body ? `body_props.${body}`:'materials.solid';
  const model = String(material?.model ?? (body ? 'linear':p.case.materials?.solid?.model ?? 'linear'));
  const quantity = (k: string, fallback: number) => {
    const q = material?.[k] as Quantity | undefined;
    return {value:Number(q?.value ?? fallback),unit:q?.unit ?? 'Pa'};
  };
  return <div className="mb-4 flex flex-col gap-3">
    <Field label={body ?? t('struct.model')}><Select ariaLabel={t('struct.model')} value={model}
      options={['linear','elastoplastic','neo-hookean'].map(v => ({value:v,label:t('model.'+v)}))} onChange={v => change(path+'.model',v)} /></Field>
    {model === 'elastoplastic' && <>{['sy','H'].map(k => {const q=quantity(k,k === 'sy' ? 250e6:2.05e9);return <Field key={k} label={t('struct.'+k)}>
      <NumberInput ariaLabel={t('struct.'+k)} value={q.value} unit={q.unit} units={['Pa','MPa','GPa']} min={0}
        onCommit={(v,u) => change(path+'.'+k,{value:v,unit:u ?? q.unit})} /></Field>;})}
      <p className="prose-ui text-label text-fg-2">{t('struct.plasticSmall')}</p></>}
  </div>;
}

/** Contact between separate parts (faces that share no nodes): detected pairs, their type and friction. */
export function ContactPairsSettings() {
  const t = useT(); const p = useStore(s => s.payload);
  // imported assemblies can gain pairs (detect); templates show them only when they define some
  if (p?.ui.physics !== 'structural' || (!p.case.template.startsWith('import-') && !p.case.contact_pairs)) return null;
  // a pair being removed is null in the optimistic payload until the server answers
  const pairs = Object.entries(p.case.contact_pairs ?? {}).filter(([, c]) => c && c.slave?.length && c.master?.length);
  const label = (k: string) => p.ui.faces.find(f => f.key === k)?.label ?? k;
  return <section className="px-4 pt-6"><SectionLabel>{t('pairs.title')}</SectionLabel>
    <p className="prose-ui mb-3 text-label text-fg-2">{t('pairs.note')}</p>
    {pairs.map(([name, c]) => <div key={name} className="mb-4 flex flex-col gap-3">
      <button className="flex min-h-8 items-center gap-2 text-left text-body text-fg" onClick={() => {selectFace(c.slave[0],'set');setState({seeThrough:true});}}>
        <span>{c.slave.map(label).join(', ')} → {c.master.map(label).join(', ')}</span></button>
      <div className="flex items-center gap-2">
        <Select ariaLabel={`${name} ${t('contact.type')}`} value={c.type} options={['bonded','frictionless','frictional','no-separation'].map(v => ({value:v,label:t('contact.'+v)}))}
          onChange={v => change(`contact_pairs.${name}.type`,v)} />
        <Button variant="ghost" size="sm" onClick={() => change(`contact_pairs.${name}`,null)}>{t('pairs.remove')}</Button>
      </div>
      {c.type === 'frictional' && <Field label={t('contact.mu')}><NumberInput ariaLabel={t('contact.mu')} value={c.mu} min={0} onCommit={v => change(`contact_pairs.${name}.mu`,v)} /></Field>}
    </div>)}
    <Button variant="secondary" size="sm" onClick={() => void detectContacts()}>{t('pairs.detect')}</Button>
  </section>;
}

export function ContactsSettings() {
  const t = useT(); const p = useStore(s => s.payload); const selected = useStore(s => s.selectedFaces);
  const faces = p?.ui.interfaces ?? [];
  if (!faces.length || p?.ui.physics !== 'structural') return null;
  const set = (face: string, field: string, value: unknown) => {
    const keys = selected.includes(face) ? faces.filter(f => selected.includes(f.key)).map(f => f.key):[face];
    for (const key of keys) change(`contacts.${key}.${field}`,value);
  };
  return <section className="px-4 pt-6"><SectionLabel>{t('contact.title')}</SectionLabel>
    <p className="prose-ui mb-3 text-label text-fg-2">{t('contact.touching')}</p>
    {faces.map(f => <div key={f.key} className="mb-4 flex flex-col gap-3">
      <button className="flex min-h-8 items-center justify-between gap-2 text-left text-body text-fg" onClick={e => {selectFace(f.key,e.shiftKey || e.ctrlKey ? 'toggle':'set');setState({seeThrough:true});}}
        aria-pressed={selected.includes(f.key)}><span>{f.bodies.join(' ↔ ')} · {f.label}</span><span className="shrink-0 rounded-[4px] bg-raised px-1.5 text-label text-fg-2">{t('contact.badge')}</span></button>
      <span className="tnum text-label text-fg-3">{f.area_m2 != null ? `${(f.area_m2*1e6).toLocaleString(undefined,{maximumFractionDigits:2})} mm²`:''}</span>
      <Select ariaLabel={`${f.label} ${t('contact.type')}`} value={f.contact.type} options={['bonded','frictionless','frictional','no-separation'].map(v => ({value:v,label:t('contact.'+v)}))}
        onChange={v => {set(f.key,'type',v);if (v === 'bonded') set(f.key,'offset',{value:0,unit:'mm'});}} />
      {f.contact.type !== 'bonded' && <>
        {f.contact.type === 'frictional' && <Field label={t('contact.mu')}><NumberInput ariaLabel={t('contact.mu')} value={f.contact.mu} min={0} onCommit={v => set(f.key,'mu',v)} /></Field>}
        <Field label={t('contact.offset')}><NumberInput ariaLabel={t('contact.offset')} value={Number(f.contact.offset.value)} unit={f.contact.offset.unit} units={['mm','m']}
          onCommit={(v,u) => set(f.key,'offset',{value:v,unit:u ?? f.contact.offset.unit})} /></Field>
      </>}
    </div>)}
  </section>;
}
