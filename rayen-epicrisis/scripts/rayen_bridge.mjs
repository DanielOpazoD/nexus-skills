import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

// Se invoca desde cua_repl después de leer la documentación CDP.
export async function runRayenEpicrisis(tab, options) {
  const url = new URL(await tab.url());
  if (url.origin !== 'https://fichamedico.rayensalud.cl' || !url.pathname.startsWith('/dashboard/')) {
    throw new Error('Inicia sesión en Registro Hospitalario con la cuenta autorizada.');
  }
  if (!options.rut || !options.from || !options.to || !options.output) throw new Error('Faltan RUN, período o salida.');
  const cdp = await tab.capabilities.get('cdp');
  const response = await cdp.send('Runtime.evaluate', {
    expression: `(async()=>{const r=await fetch('/api/auth/session',{method:'GET',cache:'no-store'});if(!r.ok)return null;const j=await r.json();if(!j.ok||!j.session?.token)return null;return {token:j.session.token,facilityId:j.session.facilityId};})()`,
    awaitPromise: true, returnByValue: true,
  });
  let session = response.result?.value;
  if (!session?.token || !Number.isInteger(session.facilityId) || session.facilityId <= 0) {
    throw new Error('Sesión no disponible; iniciar sesión y volver a intentar.');
  }
  const args = [fileURLToPath(new URL('./rayen_epicrisis.py', import.meta.url)), '--rut', options.rut,
    '--from', options.from, '--to', options.to, '--output', options.output];
  if (options.download === true) args.push('--download');
  return await new Promise((resolve, reject) => {
    const child = spawn(options.python || 'python3', args, { stdio: ['pipe', 'pipe', 'pipe'] });
    let stdout = '', stderr = '';
    child.stdout.on('data', data => { stdout += data; });
    child.stderr.on('data', data => { stderr += data; });
    child.stdin.on('error', () => {});
    child.on('error', () => { session = null; reject(new Error('No se pudo iniciar el cliente Python.')); });
    child.on('close', (code, signal) => resolve({ code, signal, stdout, stderr }));
    child.stdin.end(JSON.stringify(session));
    session = null;
  });
}
