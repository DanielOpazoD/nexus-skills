import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
const code = await readFile(new URL('../../chrome-bridge/worker.js',import.meta.url),'utf8');
async function run(sources,{missing=[],sender='http://127.0.0.1:8765/',facilityId=77}={}) {
  let listener;const sent=[];
  const chrome={action:{onClicked:{addListener(){}}},tabs:{query:async ({url}) => {
    const source=url.includes('exalab') ? 'exalab' : url.includes('clinicohangaroa') ? 'eloisa' : 'rayen';
    return missing.includes(source) ? [] : [{id:source,url:source==='rayen' ? 'https://fichamedico.rayensalud.cl/dashboard/home' : source==='eloisa' ? 'https://clinicohangaroa.eloisa.cl/main' : 'https://exalab.saludoriente.cl/web_ssmo/index.php'}];
  }},cookies:{getAll:async()=>[{name:'PHPSESSID',value:'cookie-secret'}]},
  scripting:{executeScript:async({target})=>[{result:target.tabId==='rayen' ? {token:'rayen-secret',facilityId} : 'eloisa-secret'}]},
  runtime:{onMessage:{addListener:fn=>{listener=fn;}}}};
  const context={chrome,URL,importScripts(){},navigator:{userAgent:'fixture'},AbortSignal,
    fetch:async(url,options)=>{assert.equal(url,'http://127.0.0.1:8765/api/sessions');const body=JSON.parse(options.body);sent.push(body);return {ok:true,json:async()=>({accepted:sources.filter(s=>s in body)})};}};
  vm.runInNewContext(code,context);
  let result;
  const accepted=await new Promise(resolve=>{
    const keep=listener({type:'labs.collect',sources,id:'job',nonce:'nonce'},{url:sender},body=>{result=body;resolve(true);});
    if (!keep) resolve(false);
  });
  return {sent,result,accepted};
}
test('una sesión ausente no bloquea las disponibles',async()=>{
  const r=await run(['exalab','eloisa','rayen'],{missing:['exalab']});
  assert.equal(r.sent.length,2);assert.equal(r.result.ok,true);assert.equal(r.result.errors.length,1);
  assert.deepEqual(r.sent.map(s=>Object.keys(s).filter(k=>!['id','nonce'].includes(k))).flat(),['eloisa','rayen']);
  assert.doesNotMatch(JSON.stringify(r.result),/secret/);
});
test('Rayen exige establecimiento válido',async()=>{
  const r=await run(['rayen'],{facilityId:0});assert.equal(r.sent.length,0);assert.equal(r.result.ok,false);
});
test('origen externo y origen ausente se rechazan',async()=>{
  for (const sender of ['https://evil.invalid/','http://127.0.0.1:8765.evil.invalid/',undefined]) {
    const r=await run(['eloisa'],{sender:sender===undefined ? '' : sender});assert.equal(r.accepted,false);assert.equal(r.sent.length,0);
  }
});
test('fuentes desconocidas no se consultan',async()=>{
  const r=await run(['unknown']);assert.equal(r.sent.length,0);assert.equal(r.result.ok,false);
});
