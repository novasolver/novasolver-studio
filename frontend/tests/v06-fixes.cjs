const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
function load(file, imports) {
  const compiled = ts.transpileModule(fs.readFileSync(path.join(__dirname,file),'utf8'), {
    compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX},
  }).outputText;
  const mod = {exports:{}};
  new Function('require','module','exports',compiled)(imports,mod,mod.exports);
  return mod.exports;
}
const units = load('../src/lib/units.ts',() => {throw Error('unexpected import');});
assert.equal(units.convert(1000,'N/m','N/mm'),1);
assert.equal(units.convert(1,'N/mm','N/m'),1000);
const commits = [];
const jsx = (type,props) => ({type,props:props ?? {}});
const inputs = load('../src/components/ui/Input.tsx',name => {
  if (name === 'react/jsx-runtime') return {jsx,jsxs:jsx};
  if (name === 'react') return {forwardRef:fn => fn,useState:v => [v,() => {}],useRef:v => ({current:v}),useEffect:() => {}};
  if (name === './cn') return {cn:() => ''};
  if (name === './Select') return {Select:'Select'};
  if (name === '../../lib/units') return units;
  throw Error(name);
});
function find(tree,type) {
  if (Array.isArray(tree)) return tree.flatMap(t => find(t,type));
  if (!tree || typeof tree !== 'object') return [];
  return [...(tree.type === type ? [tree]:[]),...find(tree.props.children,type)];
}
let tree = inputs.NumberInput({value:1000,unit:'N/m',units:['N/m','N/mm'],onCommit:(...v) => commits.push(v)});
find(tree,'Select')[0].props.onChange('N/mm');
assert.deepEqual(commits.pop(),[1,'N/mm']);
tree = inputs.NumberInput({value:5,unit:'N',units:['N','mm'],onCommit:(...v) => commits.push(v)});
find(tree,'Select')[0].props.onChange('mm');
assert.equal(commits.length,0,'unsupported unit change must not commit');
find(tree,'input')[0].props.onChange({target:{value:'8 mm'}});
assert.equal(commits.length,0,'typed unsupported unit change must not commit');
console.log('PASS: Spring unit conversion preserves stiffness and unsupported switches are refused.');
