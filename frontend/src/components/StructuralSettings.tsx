import { change, useStore, useT } from '../state/store';
import { NumberInput } from './ui/Input';
import { Select } from './ui/Select';
import { Field, SectionLabel } from './ui/misc';
import type { Quantity } from '../api/types';

export function VectorInput({ value, label, unit = 'mm', onCommit }: { value: number[]; label: string; unit?: string; onCommit: (v: number[]) => void }) {
  return <div className="grid grid-cols-3 gap-1">{['X','Y','Z'].map((axis,i) => <NumberInput key={axis}
    ariaLabel={`${label} ${axis}`} value={value[i] ?? 0} unit={unit}
    onCommit={v => { const next=[...value]; next[i]=v; onCommit(next); }} />)}</div>;
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
  const thermal = physics?.thermal_load?.mode ?? 'none';
  return <>
    <section className="px-4 pt-6"><SectionLabel>{t('struct.analysis')}</SectionLabel>
      <Select value={modal ? 'modal':'static'} ariaLabel={t('struct.analysis')}
        options={['static','modal'].map(v => ({value:v,label:t('struct.'+v)}))} onChange={v => change('physics.analysis',v)} />
      {modal && <div className="mt-4"><Field label={t('struct.modes')}><NumberInput ariaLabel={t('struct.modes')} value={physics?.modes ?? 6} min={1} max={30}
        onCommit={v => change('physics.modes',v)} /></Field><p className="prose-ui mt-2 text-label text-fg-2">{t('struct.loadsIgnored')}</p></div>}
    </section>
    {!modal && <>
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
