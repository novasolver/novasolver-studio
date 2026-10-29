import { useEffect, useRef, useState } from 'react';
import { Download, Play, Pause } from 'lucide-react';
import { api, exportUrl } from '../api/client';
import type { ProbeLine } from '../api/types';
import { getState, getViewer, selectMode, selectStep, setSection, setState, toast, useStore, useT } from '../state/store';
import { Button } from './ui/Button';
import { Select } from './ui/Select';
import { Slider } from './ui/Slider';
import { Field, SectionLabel } from './ui/misc';
import { VectorInput } from './StructuralSettings';
import { fmt } from '../lib/units';

function downloadCSV(text: string, name: string) {
  const url = URL.createObjectURL(new Blob([text],{type:'text/csv;charset=utf-8'}));
  const a = document.createElement('a'); a.href=url; a.download=name; a.click(); URL.revokeObjectURL(url);
}

export function ResultsTools() {
  const t = useT();
  const r = useStore(s => s.results);
  const cid = useStore(s => s.payload?.case.case_id);
  const section = useStore(s => s.section);
  const selected = useStore(s => s.selectedMode);
  const animation = useStore(s => s.modeAnimation);
  const offline = useStore(s => s.mode === 'mock');
  const [axis,setAxis] = useState(() => section ? ['x','y','z'][section.normal.findIndex(v => v === 1)] ?? 'camera':'x');
  if (!r || !cid) return null;
  const supportsSection = ['structural','modal','thermal','electrostatic','current','conjugate'].includes(r.kind ?? '');
  const plane = (a: string, p: number) => ({ normal:a === 'camera' ? getViewer()?.cameraDirection() ?? [1,0,0] : ['x','y','z'].map(v => v === a ? 1:0), position:p });
  return <>
    {!!r.curve?.length && <NonlinearResults />}
    {r.modes && <section className="px-4 pt-6"><SectionLabel>{t('modal.modes')}</SectionLabel>
      <div className="tnum overflow-x-auto rounded-[8px] bg-raised px-2 py-1 text-label">
        <table className="w-full text-right"><thead className="text-fg-2"><tr><th className="h-8 text-left font-medium">{t('modal.mode')}</th><th className="font-medium">Hz</th><th className="font-medium">Mx %</th><th className="font-medium">My %</th><th className="font-medium">Mz %</th></tr></thead>
          <tbody>{r.modes.map(m => <tr key={m.mode} className="border-t border-line text-fg">
            <td className="text-left"><button className="flex h-8 items-center gap-1" onClick={() => void selectMode(m.mode)} aria-pressed={selected === m.mode}>
              <span aria-hidden className={`h-3 w-3 rounded-full border border-line-strong ${selected === m.mode ? 'bg-fg':'bg-surface'}`} />{m.mode}</button></td>
            <td>{fmt(m.frequency_hz,5)}</td>{/* participation below 0.05 % is round-off ("1.89e-14"): show 0 so the table reads at a glance */}
            {m.effective_mass.map((v,i) => <td key={i}>{v*100 < .05 ? '0' : (v*100).toFixed(1)}</td>)}</tr>)}</tbody></table>
      </div>
      <Button variant="secondary" className="mt-3" onClick={() => setState({modeAnimation:!animation})}>
        {animation ? <Pause size={14} strokeWidth={1.5} />:<Play size={14} strokeWidth={1.5} />}{t(animation ? 'modal.pause':'modal.animate')}
      </Button><p className="prose-ui mt-2 text-label text-fg-2">{t('modal.slow')}</p>
    </section>}
    {supportsSection && !offline && <section className="px-4 pt-6"><SectionLabel>{t('section.title')}</SectionLabel>
      <label className="flex h-8 items-center gap-2 text-body text-fg"><input type="checkbox" checked={!!section}
        onChange={e => setSection(e.target.checked ? plane(axis,.5):null)} />{t('section.enabled')}</label>
      {section && <div className="mt-3 flex flex-col gap-4"><Field label={t('section.normal')}>
        <Select value={axis} ariaLabel={t('section.normal')} options={['x','y','z','camera'].map(v => ({value:v,label:v === 'camera' ? t('section.camera'):v.toUpperCase()}))}
          onChange={v => {setAxis(v);setSection(plane(v,section.position));}} /></Field>
        <Field label={t('section.position')}><Slider ariaLabel={t('section.position')} min={.01} max={.99} step={.01} value={section.position}
          onChange={v => setSection({...section,position:v})} /></Field>
        <p className="prose-ui text-label text-fg-2">{t('section.probe')}</p></div>}
    </section>}
    {!offline && supportsSection && <LinePlot key={cid} />}
    {!offline && <section className="px-4 pt-6"><SectionLabel>{t('export.title')}</SectionLabel>
      <details className="relative"><summary className="flex h-8 cursor-pointer list-none items-center gap-2 rounded-[6px] border border-line-strong px-3 text-body text-fg"><Download size={14} strokeWidth={1.5} />{t('export.menu')}</summary>
        <div className="mt-1 rounded-[6px] border border-line bg-surface py-1">{['vtu','csv','report'].map(format => <a key={format} href={exportUrl(cid,format)}
          className="flex h-8 items-center px-3 text-body text-fg-2 hover:bg-hover hover:text-fg">{t('export.'+format)}</a>)}</div>
      </details>
    </section>}
  </>;
}

function NonlinearResults() {
  const t = useT(); const r = useStore(s => s.results)!;
  const selected = useStore(s => s.selectedStep); const cid = useStore(s => s.payload?.case.case_id);
  const [playing,setPlaying] = useState(false);
  const [response,setResponse] = useState('max');
  const curve = r.curve ?? []; const step = selected ?? curve.length;
  useEffect(() => {setPlaying(false);},[cid,r.run_id]);
  useEffect(() => {
    if (!playing) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      await selectStep(step >= curve.length ? 1:step+1);
      if (!cancelled && step+1 >= curve.length) setPlaying(false);
    },350);
    return () => {cancelled=true;window.clearTimeout(timer);};
  },[playing,step,curve.length]);
  const displacement = (v: typeof curve[number]) => response === 'max' ? v.max_disp_m*1000:v.face_disp_m[Number(response)]*1000;
  const xs = curve.map(displacement), ys = curve.map(v => v.load_fraction);
  const x0 = Math.min(0,...xs),x1 = Math.max(...xs),y0 = Math.min(0,...ys),y1 = Math.max(...ys);
  const points = curve.map(v => `${30+(displacement(v)-x0)/(x1-x0 || 1)*220},${108-(v.load_fraction-y0)/(y1-y0 || 1)*88}`);
  return <section className="px-4 pt-6"><SectionLabel>{t('nonlinear.steps')}</SectionLabel>
    <div className="tnum mb-2 text-body text-fg-2">{t('nonlinear.step',{step,n:curve.length})} · {t('nonlinear.load')} {fmt(curve[step-1]?.load_fraction ?? 0,4)}</div>
    <Slider ariaLabel={t('nonlinear.steps')} min={1} max={curve.length} step={1} value={step} onChange={v => {setPlaying(false);void selectStep(v);}} />
    <Button variant="secondary" className="mt-3" onClick={() => {if (step >= curve.length) void selectStep(1);setPlaying(v => !v);}}>
      {playing ? <Pause size={14} strokeWidth={1.5} />:<Play size={14} strokeWidth={1.5} />}{t(playing ? 'modal.pause':'nonlinear.play')}</Button>
    <div className="mt-6"><SectionLabel>{t('nonlinear.curve')}</SectionLabel>
      <Select ariaLabel={t('nonlinear.response')} value={response} options={['max','0','1','2'].map(v => ({value:v,label:t(v === 'max' ? 'nonlinear.max':'nonlinear.face'+v)}))} onChange={setResponse} />
      <svg viewBox="0 0 264 142" role="img" aria-label={t('nonlinear.curve')} className="mt-3 block w-full">
        <path d="M30 14 V108 H250" fill="none" stroke="var(--line-strong)" />
        <polyline points={points.join(' ')} fill="none" stroke="var(--text-2)" strokeWidth="1.5" />
        {points[step-1] && <circle cx={Number(points[step-1].split(',')[0])} cy={Number(points[step-1].split(',')[1])} r="3" fill="var(--text)" />}
        <text x="3" y="20" fontSize="11" fill="var(--text-3)">{fmt(y1,3)}</text><text x="3" y="108" fontSize="11" fill="var(--text-3)">{fmt(y0,3)}</text>
        <text x="30" y="130" fontSize="11" fill="var(--text-3)">{fmt(x0,3)}</text><text x="250" y="130" textAnchor="end" fontSize="11" fill="var(--text-3)">{fmt(x1,3)} mm</text>
      </svg>
      <Button variant="ghost" onClick={() => downloadCSV(['step,load_fraction,max_disp_m,face_ux_m,face_uy_m,face_uz_m',...curve.map(v => [v.step,v.load_fraction,v.max_disp_m,...v.face_disp_m].join(','))].join('\n'),'load-displacement.csv')}>
        <Download size={14} strokeWidth={1.5} />{t('line.csv')}</Button>
    </div>
  </section>;
}

function LinePlot() {
  const t = useT();
  const cid = useStore(s => s.payload!.case.case_id);
  const bbox = useStore(s => s.geometry?.bbox);
  const mode = useStore(s => s.selectedMode);
  const selectedStep = useStore(s => s.selectedStep);
  const runId = useStore(s => s.results?.run_id);
  const [from,setFrom] = useState([0,0,0]), [to,setTo] = useState([100,0,0]);
  const [data,setData] = useState<ProbeLine | null>(null);
  const [quantity,setQuantity] = useState('');
  const [busy,setBusy] = useState(false);
  const generation = useRef(0);
  useEffect(() => {
    setData(null); setBusy(false);
    return () => { generation.current++; };
  }, [cid,mode,selectedStep,runId]);
  useEffect(() => {
    if (!bbox) return;
    const ext = bbox[0].map((v,i) => bbox[1][i]-v);
    const axis = ext.indexOf(Math.max(...ext));
    const a = bbox[0].map((v,i) => (v+bbox[1][i])*500), b = [...a];
    a[axis] = bbox[0][axis]*1000; b[axis] = bbox[1][axis]*1000;
    setFrom(a);setTo(b);
  }, [bbox]);
  const run = async () => {
    const token = ++generation.current;
    const current = () => {
      const state = getState();
      return generation.current === token && state.payload?.case.case_id === cid &&
        state.results?.run_id === runId && state.selectedMode === mode && state.selectedStep === selectedStep;
    };
    setBusy(true);
    try {
      const r = await api.probe(cid,{from,to,n:80},mode,runId,selectedStep);
      if (current()) { setData(r); setQuantity(Object.keys(r.quantities)[0]); }
    }
    catch(e) { if (current()) toast(e instanceof Error ? e.message:String(e),'error'); }
    finally { if (current()) setBusy(false); }
  };
  const samples = data?.line.samples ?? [];
  const vals = samples.filter(s => s.inside).map(s => s.values[quantity]).filter(Number.isFinite);
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi-lo || Math.abs(hi)*.1 || 1;
  const length = data ? Math.hypot(...data.line.to_mm.map((v,i) => v-data.line.from_mm[i])) : 0;
  const path = samples.map((s,i) => `${i === 0 || !samples[i-1].inside ? 'M':'L'}${30+i/Math.max(samples.length-1,1)*220},${100-(s.values[quantity]-lo)/span*80}`);
  return <section className="px-4 pt-6"><SectionLabel>{t('line.title')}</SectionLabel>
    <details><summary className="h-8 cursor-pointer text-body text-fg-2">{t('line.define')}</summary>
      <div className="mt-3 flex flex-col gap-4"><Field label={t('line.from')}><VectorInput label={t('line.from')} value={from} onCommit={setFrom} /></Field>
        <Field label={t('line.to')}><VectorInput label={t('line.to')} value={to} onCommit={setTo} /></Field>
        <Button variant="secondary" disabled={busy} onClick={() => void run()}>{t('line.plot')}</Button></div></details>
    {data && <div className="mt-3"><Select value={quantity} ariaLabel={t('results.quantity')} options={Object.entries(data.quantities).map(([q,u]) => ({value:q,label:`${q} [${u}]`}))} onChange={setQuantity} />
      {vals.length > 0 && <svg viewBox="0 0 264 126" role="img" aria-label={t('line.chart')} className="mt-3 block w-full">
        <path d="M30 10 V100 H250" fill="none" stroke="var(--line-strong)" />
        <path d={samples.map((s,i) => s.inside ? path[i]:'').join(' ')} fill="none" stroke="var(--text-2)" strokeWidth="1.5" />
        <text x="3" y="18" fontSize="11" fill="var(--text-3)">{fmt(hi,3)}</text><text x="3" y="100" fontSize="11" fill="var(--text-3)">{fmt(lo,3)}</text>
        <text x="30" y="119" fontSize="11" fill="var(--text-3)">0</text><text x="250" y="119" textAnchor="end" fontSize="11" fill="var(--text-3)">{fmt(length,4)} mm</text>
      </svg>}
      <Button variant="ghost" className="mt-2" onClick={() => {
        const keys=Object.keys(data.quantities);
        const text=[['x_mm','y_mm','z_mm','inside',...keys.map(k => `${k} [${data.quantities[k]}]`)].join(','),...samples.map(s => [...s.at_mm,s.inside,...keys.map(k => s.values[k])].join(','))].join('\n');
        downloadCSV(text,'probe-line.csv');
      }}><Download size={14} strokeWidth={1.5} />{t('line.csv')}</Button>
    </div>}
  </section>;
}
