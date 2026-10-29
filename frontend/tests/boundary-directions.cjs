const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const source = fs.readFileSync(path.join(__dirname, '../src/components/PropertiesPanel.tsx'), 'utf8');
const compiled = ts.transpileModule(source+'\nexport { SelectionEditor };', {
  compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX},
}).outputText;
const directions = ['+x', '-x', '+y', '-y', '+z', '-z', 'normal'].map(id => ({id, label: id}));
let state;
const mod = {exports: {}};
const jsx = (type, props) => ({type, props: props ?? {}});
new Function('require', 'module', 'exports', compiled)(name => {
  if (name === 'react/jsx-runtime') return {jsx, jsxs: jsx};
  if (name === '../state/store') return {useStore: fn => fn(state), useT: () => key => key};
  return new Proxy({}, {get: (_, key) => key});
}, mod, mod.exports);
function find(tree) {
  if (Array.isArray(tree)) return tree.flatMap(find);
  if (!tree || typeof tree !== 'object') return [];
  return [...(tree.type === 'Select' && tree.props.ariaLabel === 'Direction' ? [tree] : []), ...find(tree.props.children)];
}
for (const role of ['load', 'moment', 'bearing', 'remote-force']) {
  state = {selectedFaces: ['x1'], fieldErrors: {}, payload: {case: {}, ui: {
    faces: [{key: 'x1', role, label: 'Face', values: {direction: '+z'}}], roles: [], params: [], directions,
    role_fields: {[role]: ['direction']}, field_labels: {direction: 'Direction'},
  }}};
  const picker = find(mod.exports.SelectionEditor())[0];
  assert.ok(picker);
  assert.equal(picker.props.options.some(d => d.value === 'normal'), role === 'load', role);
}
console.log('PASS: The direction picker offers normal only for a load role.');
require('./v06-fixes.cjs');
