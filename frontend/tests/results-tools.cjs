// Exercise the real LinePlot with deferred network replies and a minimal React hook host.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const source = fs.readFileSync(path.join(__dirname, '../src/components/ResultsTools.tsx'), 'utf8');
const compiled = ts.transpileModule(source+'\nexport { LinePlot };', {
  compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX},
}).outputText;
const tick = () => new Promise(resolve => setImmediate(resolve));
function host() {
  let state = {payload: {case: {case_id: 'c_one'}}, results: {run_id: 'j_one'}, selectedMode: 1};
  let cursor = 0, slots = [], effects = [], pending = [], requests = [], errors = [];
  const hook = initial => {
    const i = cursor++;
    if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial;
    return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }];
  };
  const react = {useState: hook, useRef: initial => hook(() => ({current: initial}))[0], useEffect: (fn, deps) => {
    const i = cursor++, old = effects[i];
    if (!old || deps.some((v, k) => v !== old.deps[k])) {
      pending.push(() => { old?.cleanup?.(); effects[i] = {deps, cleanup: fn()}; });
    }
  }};
  const store = {useStore: fn => fn(state), getState: () => state, useT: () => key => key, toast: (...args) => errors.push(args)};
  const api = {probe: (...args) => new Promise((resolve, reject) => requests.push({args, resolve, reject}))};
  const mod = {exports: {}};
  const jsx = (type, props) => ({type, props: props ?? {}});
  new Function('require', 'module', 'exports', compiled)(name => {
    if (name === 'react') return react;
    if (name === 'react/jsx-runtime') return {jsx, jsxs: jsx};
    if (name === '../state/store') return store;
    if (name === '../api/client') return {api};
    if (name === '../lib/units') return {fmt: String};
    return new Proxy({}, {get: (_, key) => key});
  }, mod, mod.exports);
  const render = () => { cursor = 0; const tree = mod.exports.LinePlot(); pending.splice(0).forEach(fn => fn()); return tree; };
  const find = (tree, test) => {
    if (Array.isArray(tree)) return tree.flatMap(t => find(t, test));
    if (!tree || typeof tree !== 'object') return [];
    return [...(test(tree) ? [tree] : []), ...find(tree.props?.children, test)];
  };
  return {render, find, requests, errors, state,
    start: () => find(render(), el => el.props.children === 'line.plot')[0].props.onClick(),
    unmount: () => effects.forEach(e => e?.cleanup?.())};
}
const reply = {case_id: 'c_one', run_id: 'j_one', quantities: {mode: '-'},
  line: {from_mm: [0, 0, 0], to_mm: [100, 0, 0], samples: [
    {inside: true, at_mm: [0, 0, 0], values: {mode: .1}},
    {inside: true, at_mm: [100, 0, 0], values: {mode: .2}},
  ]}};
(async () => {
  for (const selection of ['mode', 'run', 'case', 'unmount']) {
    const h = host(); h.start();
    if (selection === 'mode') h.state.selectedMode = 2;
    if (selection === 'run') h.state.results.run_id = 'j_two';
    if (selection === 'case') h.state.payload.case.case_id = 'c_two';
    if (selection === 'unmount') h.unmount(); else h.render();
    h.requests[0].resolve(reply); await tick();
    const chart = h.find(h.render(), el => el.props['aria-label'] === 'line.chart');
    assert.equal(chart.length, 0, `late ${selection} response must be discarded`);
  }
  const h = host(); h.start(); h.requests[0].resolve(reply); await tick();
  assert.equal(h.find(h.render(), el => el.props['aria-label'] === 'line.chart').length, 1);
  // A stale rejection/finally must not clear the new request's busy state or show an old error.
  const e = host(); e.start(); e.state.selectedMode = 2; e.render(); e.start();
  e.requests[0].reject(new Error('old mode failed')); await tick();
  assert.equal(e.errors.length, 0);
  assert.equal(e.find(e.render(), el => el.props.children === 'line.plot')[0].props.disabled, true);
  e.requests[1].resolve(reply); await tick();
  assert.equal(e.find(e.render(), el => el.props['aria-label'] === 'line.chart').length, 1);
  console.log('PASS: Probe responses, errors and busy state respect case/run/mode generations and unmount.');
})().catch(error => {console.error(error); process.exitCode = 1;});
