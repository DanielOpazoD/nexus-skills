import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,chmod,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {runRayenEpicrisis} from '../rayen_bridge.mjs';
const tab = (value, url='https://fichamedico.rayensalud.cl/dashboard/reports') => ({
  url:async()=>url,capabilities:{get:async()=>({send:async()=>({result:{value}})})}
});
test('sesión solo por stdin, sin secretos en argumentos ni resultado',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'rayen-bridge-'));
 try {
  const fake=join(dir,'fake-python');
  await writeFile(fake,'#!'+process.execPath+'\n'+`let s='';process.stdin.on('data',c=>s+=c);process.stdin.on('end',()=>{const p=JSON.parse(s);console.log(JSON.stringify({valid:p.token==='fixture-token'&&p.facilityId===77,secretInArgs:process.argv.includes('fixture-token'),download:process.argv.includes('--download')}));});`);
  await chmod(fake,0o700);
  const r=await runRayenEpicrisis(tab({token:'fixture-token',facilityId:77}),{rut:'11111111-1',from:'2026-10-01',to:'2026-10-19',output:dir,python:fake,download:true});
  assert.equal(r.code,0);assert.deepEqual(JSON.parse(r.stdout),{valid:true,secretInArgs:false,download:true});
 } finally{await rm(dir,{recursive:true,force:true});}
});
test('otro origen no recibe ni solicita sesión',async()=>{
 await assert.rejects(runRayenEpicrisis(tab(null,'https://other.example/dashboard/reports'),{}),/Inicia sesión/);
});
test('sesión ausente requiere autenticación, no lanza el cliente',async()=>{
 await assert.rejects(runRayenEpicrisis(tab(null),{rut:'11111111-1',from:'2026-10-01',to:'2026-10-19',output:'/tmp'}),/Sesión no disponible/);
});
