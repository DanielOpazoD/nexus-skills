import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runLabs, writeLabsSession } from '../laboratorios_chrome_bridge.mjs';

// Proceso falso: verifica el transporte sin ejecutar Python ni acceder a portales.
const fakeProgram = `
let text = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => text += chunk);
process.stdin.on('end', () => {
  const payload = JSON.parse(text);
  const argv = process.argv.slice(2);
  if (argv.some(arg => arg.includes('fixture-secret'))) process.exit(3);
  const correctCredentials = ['syslab', 'mmrad', 'his'].every(key => !payload[key] ||
    (payload[key].username === 'fixture-user' && payload[key].password === 'fixture-secret'));
  console.log(JSON.stringify({ keys: Object.keys(payload).sort(), correctCredentials, argv }));
});`;
const credentials = { username: 'fixture-user', password: 'fixture-secret' };
async function invoke(source, options = {}, secrets = {}, tabs = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'clinical-bridge-test-'));
  try {
    const script = join(dir, 'fake-python.cjs');
    await writeFile(script, fakeProgram);
    const result = await runLabs(tabs, {
      source, period: '6m', output: dir, ruts: ['11111111-1'],
      script, python: process.execPath, ...options,
    }, secrets);
    assert.equal(result.code, 0, result.stderr);
    assert.equal(result.timedOut, false);
    return JSON.parse(result.stdout);
  } finally { await rm(dir, { recursive: true, force: true }); }
}

test('HIS se selecciona y recibe sus credenciales por stdin', async () => {
  const result = await invoke('his', { merge: true, resume: '/fixture/avance.json' }, { his: credentials });
  assert.deepEqual(result.keys, ['his']);
  assert.equal(result.correctCredentials, true);
  assert.ok(result.argv.includes('--merge'));
  assert.ok(result.argv.includes('/fixture/avance.json'));
  assert.equal(result.argv[result.argv.indexOf('--source') + 1], 'his');
});
test('all incluye el transporte de HIS y conserva opciones MMRAD', async () => {
  const result = await invoke('all', { mmradMode: 'reports' }, {
    his: credentials, mmrad: credentials, syslab: credentials,
  });
  assert.deepEqual(result.keys, ['his', 'mmrad', 'syslab']);
  assert.equal(result.correctCredentials, true);
  assert.equal(result.argv[result.argv.indexOf('--mmrad-mode') + 1], 'reports');
});
test('una lista explícita acepta HIS junto con otro sitio', async () => {
  const result = await invoke('syslab,his', {}, { his: credentials, syslab: credentials });
  assert.deepEqual(result.keys, ['his', 'syslab']);
});
test('both mantiene Syslab y Exalab y no transmite HIS', async () => {
  const result = await invoke('both', {}, { syslab: credentials, his: credentials });
  assert.deepEqual(result.keys, ['syslab']);
  assert.equal(result.argv.includes('--mmrad-mode'), false);
});
test('fuentes inválidas y duplicadas se rechazan antes de ejecutar', async () => {
  await assert.rejects(invoke('his,his'), /Fuentes inválidas/);
  await assert.rejects(invoke('unknown'), /Fuentes inválidas/);
});
test('Exalab sin sesión continúa informando autenticación pendiente', async () => {
  const result = await invoke('exalab');
  assert.deepEqual(result.keys, []); // Python clasifica la sesión ausente sin cancelar otras fuentes.
});

test('renueva una vez, reanuda solo la fuente fallida y no repite indefinidamente', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'recovery-test-'));
  try {
    const script = join(dir, 'fake.cjs');
    await writeFile(script, `process.stdin.resume();process.stdin.on('end',()=>{console.log('CLINICAL_RESULT '+JSON.stringify({checkpoint:'/fixture/avance.json',auth_sources:['eloisa']}));process.exitCode=2;});`);
    let renewals=0;
    const result=await runLabs({}, {source:'eloisa',period:'6m',output:dir,ruts:['11111111-1'],script,python:process.execPath,
      reauthenticate:async()=>{renewals++;return {url:async()=> 'https://clinicohangaroa.eloisa.cl/'};}});
    assert.equal(renewals,1);assert.equal(result.rounds.length,2);assert.equal(result.code,2);
  } finally {await rm(dir,{recursive:true,force:true});}
});
test('pestaña cerrada no impide transportar credenciales de otra fuente', async()=>{
  const result=await invoke('exalab,his',{}, {his:credentials}, {exalab:{url:async()=>{throw Error('closed')}}});
  assert.deepEqual(result.keys,['his']);
});

test('FIFO entrega sesión en memoria y rechaza archivos regulares', async()=>{
  const dir=await mkdtemp(join(tmpdir(),'session-pipe-test-'));
  try {
    const regular=join(dir,'regular');await writeFile(regular,'keep',{mode:0o600});
    await assert.rejects(writeLabsSession({}, {source:'his'},regular,{his:credentials}), /FIFO/);
    assert.equal(await readFile(regular,'utf8'),'keep');
    const {execFileSync}=await import('node:child_process');const pipe=join(dir,'pipe');
    execFileSync('/usr/bin/mkfifo',['-m','600',pipe]);
    const reading=readFile(pipe,'utf8');
    const result=await writeLabsSession({}, {source:'his'},pipe,{his:credentials});
    assert.deepEqual(JSON.parse(await reading),{his:credentials});
    assert.deepEqual(result.sessions,['his']);assert.equal(JSON.stringify(result).includes('fixture-secret'),false);
  } finally {await rm(dir,{recursive:true,force:true});}
});

test('MMRAD transporta los tipos de imagen seleccionados y rechaza tipos desconocidos', async () => {
  const result = await invoke('mmrad', {mmradMode:'images',mmradImageTypes:['radiographs']}, {mmrad:credentials});
  assert.equal(result.argv[result.argv.indexOf('--mmrad-image-types')+1], 'radiographs');
  await assert.rejects(invoke('mmrad',{mmradImageTypes:['CT']},{mmrad:credentials}), /Tipos de imágenes/);
});

test('solicitud portátil conserva períodos propios, referencia y productos al ejecutar', async () => {
  const result=await invoke('eloisa,rayen,mmrad',{period:'3m',sourcePeriods:{rayen:'10y',mmrad:'latest'},asOf:'2026-10-19',mmradMode:'images',mmradImageTypes:['radiographs']});
  const value=flag=>result.argv[result.argv.indexOf(flag)+1];
  assert.equal(value('--period'),'3m');assert.equal(value('--as-of'),'2026-10-19');
  assert.deepEqual(JSON.parse(value('--source-periods')),{rayen:'10y',mmrad:'latest'});
  assert.equal(value('--mmrad-mode'),'images');assert.equal(value('--mmrad-image-types'),'radiographs');
  await assert.rejects(invoke('eloisa',{sourcePeriods:{syslab:'10y'}}),/Períodos por fuente/);
  await assert.rejects(invoke('eloisa',{sourcePeriods:{eloisa:'20y'}}),/Períodos por fuente/);
});

test('contenido por fuente llega al CLI y rechaza selecciones ambiguas', async () => {
  const content={eloisa:['prescriptions','referrals'],rayen:['epicrisis','record']};
  const result=await invoke('eloisa,rayen',{sourceContent:content});
  assert.deepEqual(JSON.parse(result.argv[result.argv.indexOf('--source-content')+1]),content);
  for (const sourceContent of [{eloisa:[]},{rayen:['record']},{eloisa:['medical','medical']}]) {
    await assert.rejects(invoke('eloisa',{sourceContent}), /Contenido por fuente/);
  }
});

test('correo conserva cuenta y período sin pedir sesión de Chrome',async()=>{
  const result=await invoke('email',{emailAccount:'daniel.opazo@hospitalhangaroa.cl',sourcePeriods:{email:'3m'}});
  assert.deepEqual(result.keys,[]);
  assert.equal(result.argv[result.argv.indexOf('--email-account')+1],'daniel.opazo@hospitalhangaroa.cl');
  assert.equal(result.argv[result.argv.indexOf('--source-periods')+1],'{"email":"3m"}');
});


test('catálogo transmite adjuntos y filtro TAC sin ampliación implícita',async()=>{
  const content={eloisa:['attachments'],mmrad:['ct_reports']};
  const result=await invoke('eloisa,mmrad',{sourceContent:content,mmradMode:'both',mmradImageTypes:['radiographs']});
  assert.deepEqual(JSON.parse(result.argv[result.argv.indexOf('--source-content')+1]),content);
  assert.equal((await invoke('eloisa')).argv.includes('--source-content'),false);
  await assert.rejects(invoke('eloisa',{sourceContent:{eloisa:['unknown']}}),/Contenido/);
});
