// Headless store regressions; browser picking and visual acceptance are checked separately.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const ts = require('typescript');
const timers = new Map();
let timerId=0;
global.window = { matchMedia: () => ({matches:false}), clearTimeout:id=>timers.delete(id),
 setTimeout:fn=>{timers.set(++timerId,fn);return timerId;}, prompt:()=>null };
global.localStorage={getItem:()=>null};
const qty=value=>({value,unit:'N'});
const base=()=>({case:{case_id:'c_test',revision:1,title:{en:'Test'},template:'cantilever',face_groups:{}},
 ui:{params:[],roles:[{id:'free',label:'Free'}],faces:[{key:'x1',label:'Face 1',role:'free',values:{force:qty(1000)}}]},jobs:[],steps:{}});
let server=base();
const calls=[];
let releaseFirst;
let first=true;
const api={
 patchCase:async(id,rev,changes)=>{
  calls.push(['patch',rev]); assert.equal(rev,server.case.revision);
  if(first){first=false;await new Promise(resolve=>releaseFirst=resolve);}
  server=structuredClone(server);server.case.revision++;
  server.ui.faces[0].values.force=changes['boundaries.x1.force'];
  return structuredClone(server);
 },
 undo:async(id,rev)=>{calls.push(['undo',rev]);assert.equal(rev,server.case.revision);server=structuredClone(server);
  server.case.revision++;server.undone={source:'gui',summary:'Force',paths:['boundaries.x1.force']};return server;},
 geometry:async()=>({faces:[]}),guiState:async()=>{},
};
const client={api,ApiError:class extends Error{},isMock:()=>false,faceRolePath:k=>`boundaries.${k}.role`};
const translations={detectLang:()=> 'en',pick:(lang,title)=>title?.[lang],translate:(lang,key)=>key};
const source=fs.readFileSync(require('node:path').join(__dirname,'../src/state/store.ts'),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const mod={exports:{}};
new Function('require','module','exports',compiled)(name=>{
 if(name==='react')return {useCallback:f=>f,useSyncExternalStore:()=>{}};
 if(name==='../api/client')return client;
 if(name==='../i18n')return translations;
 throw new Error('Unexpected import '+name);
},mod,mod.exports);
const S=mod.exports;
(async()=>{
 S.setState({payload:base()});
 S.change('boundaries.x1.force',qty(100));
 const pendingUndo=S.undoCase();
 assert.equal(calls.length,1);
 S.change('boundaries.x1.force',qty(200));
 releaseFirst();
 await pendingUndo;
 assert.deepEqual(calls,[['patch',1],['patch',2],['undo',3]]);
 assert.equal(S.getState().payload.case.revision,4);
 assert.equal(S.getState().toast.action,'redo');
 console.log('PASS: Undo drains edits arriving during autosave before reading its expected revision.');
 const f=(key,descriptor)=>({key,label:key,role:'free',area_m2:1,descriptor:{key,...descriptor}});
 const faces=[f('a',{type:'Plane',normal:[0,0,1],smooth_neighbors:['b']}),
  f('b',{type:'Plane',normal:[0,0,1],smooth_neighbors:['a','c']}),
  f('c',{type:'Plane',normal:[0,1,0],smooth_neighbors:['b']}),
  f('d',{type:'Cylinder',axis:[0,0,1],axis_point:[0,0,0],radius:1}),
  f('e',{type:'Cylinder',axis:[0,0,-1],axis_point:[0,0,10],radius:2}),
  f('f',{type:'Cylinder',axis:[0,0,1],axis_point:[1,0,0],radius:1})];
 S.setState({payload:{...base(),ui:{...base().ui,faces}},geometry:{faces:[],bbox:[[0,0,0],[10,10,10]]}});
 S.selectFaces(['a']);S.selectConnected();assert.deepEqual(S.getState().selectedFaces,['a','b','c']);
 S.selectFaces(['a']);S.selectSameDirection();assert.deepEqual(S.getState().selectedFaces,['a','b']);
 S.selectFaces(['d']);S.selectCoaxial();assert.deepEqual(S.getState().selectedFaces,['d','e']);
 S.selectCoaxial();assert.deepEqual(S.getState().selectedFaces,['d']);
 S.setState({faceFilter:['a','b','c']});S.selectFaces(['a']);S.invertSelection();assert.deepEqual(S.getState().selectedFaces,['b','c']);
 S.hideSelected();assert.deepEqual(S.getState().hiddenFaces,['b','c']);assert.equal(S.getState().selectedFaces.length,0);
 S.showAllFaces();assert.equal(S.getState().hiddenFaces.length,0);S.toggleSeeThrough();assert.equal(S.getState().seeThrough,true);
 console.log('PASS: Connected, direction, coaxial/radius, filtered inversion, hide/show and see-through actions.');
 let resolvePoint, pointArgs;
 api.probePoint=(...args)=>{pointArgs=args;return new Promise(resolve=>resolvePoint=resolve);};
 S.setState({payload:base(),results:{run_id:'j_one'},selectedMode:1,mode:'backend',
  field:{quantity:'uz',section:{normal:[1,0,0],position:.25}}});
 const at=[.25,.1,.1];
 const point=S.probeFieldPoint(at,125,'mm');
 assert.deepEqual(pointArgs,['c_test',[250,100,100],1,'j_one',null]);
 resolvePoint({points:[{inside:true,values:{uz:62.5}}]});await point;
 assert.deepEqual(S.getState().probeValue,{at,value:62.5,unit:'mm'});
 const stale=S.probeFieldPoint(at,125,'mm');
 S.setState({selectedMode:2});S.setState({selectedMode:1});
 resolvePoint({points:[{inside:true,values:{uz:999}}]});await stale;
 assert.equal(S.getState().probeValue,null);
 S.setState({selectedStep:3});
 const stepProbe=S.probeFieldPoint(at,125,'mm');
 assert.equal(pointArgs[4],3);
 S.setState({selectedStep:2});
 resolvePoint({points:[{inside:true,values:{uz:999}}]});await stepProbe;
 assert.equal(S.getState().probeValue,null);
 console.log('PASS: Section clicks query the original element and discard stale point responses.');
})().catch(e=>{console.error(e);process.exitCode=1});
