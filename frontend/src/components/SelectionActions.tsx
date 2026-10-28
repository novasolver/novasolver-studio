import { Copy, Eye, EyeOff, FlipHorizontal, GitBranch, Layers, MoveUp, Palette, Save, Scan } from 'lucide-react';
import { hideSelected, invertSelection, saveFaceGroup, selectCoaxial, selectConnected, selectSameColor, selectSameDirection,
  selectSimilar, showAllFaces, toggleSeeThrough, useStore, useT } from '../state/store';
import { Tooltip } from './ui/Tooltip';

export function SelectionActions({ groups = false }: { groups?: boolean }) {
  const t = useT();
  const selected = useStore(s => s.selectedFaces);
  const faces = useStore(s => s.payload?.ui.faces);
  const hidden = useStore(s => s.hiddenFaces);
  const through = useStore(s => s.seeThrough);
  const descriptors = faces?.filter(f => selected.includes(f.key)).map(f => f.descriptor);
  const actions = [
    ...(selected.length ? [
      ...(faces?.some(f => selected.includes(f.key) && f.area_m2) ? [{ key: 'bc.similar', icon: Copy, run: selectSimilar }] : []),
      ...(descriptors?.some(d => d?.smooth_neighbors) ? [{ key: 'bc.connected', icon: GitBranch, run: selectConnected }] : []),
      ...(descriptors?.some(d => d?.normal) ? [{ key: 'bc.direction', icon: MoveUp, run: selectSameDirection }] : []),
      ...(descriptors?.some(d => d?.axis && d.axis_point && d.radius) ? [{ key: 'bc.coaxial', hint: 'bc.coaxialHint', icon: Scan, run: selectCoaxial }] : []),
      ...(descriptors?.some(d => d?.color) ? [{ key: 'bc.sameColor', icon: Palette, run: selectSameColor }] : []),
      { key: 'bc.invert', icon: FlipHorizontal, run: invertSelection },
      { key: 'bc.hide', icon: EyeOff, run: hideSelected },
      ...(groups ? [{ key: 'bc.saveGroup', icon: Save, run: () => saveFaceGroup() }] : []),
    ] : []),
    ...(hidden.length ? [{ key: 'bc.showAll', icon: Eye, run: showAllFaces }] : []),
    { key: 'bc.seeThrough', icon: Layers, run: toggleSeeThrough },
  ];
  if (groups) {
    // in the properties panel there is room to name every action: icon-only buttons hid what each one does
    return <div className="grid grid-cols-2 gap-0.5">
      {actions.map(a => <button key={a.key} type="button" title={'hint' in a && a.hint ? t(a.hint) : undefined}
        aria-pressed={a.key === 'bc.seeThrough' ? through : undefined} onClick={a.run}
        className="flex h-8 min-w-0 items-center gap-1.5 rounded-[6px] px-2 text-left text-label text-fg-2 hover:bg-hover hover:text-fg aria-pressed:bg-active aria-pressed:text-fg">
        <a.icon size={14} strokeWidth={1.5} className="shrink-0 text-fg-3" />
        <span className="truncate">{t(a.key)}</span>
      </button>)}
    </div>;
  }
  return <div className="flex flex-wrap items-center gap-0.5">
    {actions.map(a => <Tooltip key={a.key} content={t('hint' in a && a.hint ? a.hint : a.key)}>
      <button type="button" aria-label={t(a.key)} aria-pressed={a.key === 'bc.seeThrough' ? through : undefined}
        onClick={a.run} className="flex h-8 w-8 items-center justify-center rounded-[6px] text-fg-2 hover:bg-hover hover:text-fg aria-pressed:bg-active">
        <a.icon size={15} strokeWidth={1.5} />
      </button>
    </Tooltip>)}
  </div>;
}
