import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { lstat, open, readFile } from 'node:fs/promises';
import { constants } from 'node:fs';
import { dirname } from 'node:path';

async function runOnce(tab, options, secrets = {}) {
  // Sin límite total por defecto; Python mantiene sus tiempos de espera de red.
  const timeoutMs = options.timeoutMs ?? 0;
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 0 || timeoutMs > 2147483647) {
    throw new Error('timeoutMs debe ser un entero entre 0 (sin límite total) y 2147483647.');
  }
  const {payload, selected} = await collectSessions(tab, options, secrets);
  const script = options.script || fileURLToPath(new URL('./laboratorios_download.py', import.meta.url));
  const args = [script, '--session-stdin', '--source', options.source, '--period', options.period, '--output', options.output, '--ruts', ...options.ruts];
  if (selected.includes('mmrad')) args.push('--mmrad-mode', options.mmradMode || 'both');
  if (selected.includes('mmrad') && options.mmradImageTypes !== undefined) {
    if (!Array.isArray(options.mmradImageTypes) || options.mmradImageTypes.some(x => !['radiographs','ultrasounds'].includes(x))) throw new Error('Tipos de imágenes MMRAD inválidos.');
    args.push('--mmrad-image-types', options.mmradImageTypes.join(','));
  }
  if (selected.includes('email')) args.push('--email-account',options.emailAccount || 'daniel.opazo@hospitalhangaroa.cl');
  if (options.merge) args.push('--merge');
  if (options.patientMerge) args.push('--patient-merge');
  if (options.eloisaScope) args.push('--eloisa-scope', options.eloisaScope);
  if (options.asOf) args.push('--as-of', options.asOf);
  if (options.sourcePeriods !== undefined) {
    const periods = ['30d','3m','6m','1y','2y','5y','10y','latest'];
    if (!options.sourcePeriods || typeof options.sourcePeriods !== 'object' || Array.isArray(options.sourcePeriods) ||
        Object.entries(options.sourcePeriods).some(([source, period]) => !selected.includes(source) || !periods.includes(period))) {
      throw new Error('Períodos por fuente inválidos.');
    }
    args.push('--source-periods', JSON.stringify(options.sourcePeriods));
  }
  if (options.sourceContent !== undefined) {
    const catalog=JSON.parse(await readFile(new URL('../assets/clinical_catalog.json',import.meta.url),'utf8'));
    const types=Object.fromEntries(Object.entries(catalog.content).map(([source,items])=>[source,items.map(x=>x.id)]));
    if (!options.sourceContent || typeof options.sourceContent !== 'object' || Array.isArray(options.sourceContent) ||
        Object.entries(options.sourceContent).some(([source, items]) => !selected.includes(source) || !types[source] ||
          !Array.isArray(items) || !items.length || new Set(items).size !== items.length || items.some(x => !types[source].includes(x)))) {
      throw new Error('Contenido por fuente inválido.');
    }
    args.push('--source-content', JSON.stringify(options.sourceContent));
  }
  if (options.listOnly) args.push('--list-only');
  if (options.resume) args.push('--resume', options.resume);
  if (options.fresh) args.push('--fresh');
  if (options.retryUnavailable) args.push('--retry-unavailable');
  if (options.retrySources) args.push('--retry-sources', options.retrySources);
  if (options.imageWorkers) args.push('--image-workers', String(options.imageWorkers));
  if (options.eloisaBounded === false) args.push('--eloisa-full-history');
  return await new Promise((resolve, reject) => {
    const child = spawn(options.python || 'python3', args, { stdio: ['pipe', 'pipe', 'pipe'] });
    let stdout = '', stderr = '';
    let timedOut = false;
    const timer = timeoutMs > 0 ? setTimeout(() => { timedOut = true; child.kill('SIGTERM'); }, timeoutMs) : null;
    child.stdout.on('data', chunk => { stdout += chunk; });
    child.stderr.on('data', chunk => { stderr += chunk; });
    child.on('error', error => { clearTimeout(timer); reject(error); });
    child.on('close', (code, signal) => { clearTimeout(timer); resolve({ code, signal, timedOut, stdout, stderr }); });
    child.stdin.on('error', () => {});
    child.stdin.end(JSON.stringify(payload));
  });
}

// El callback usa la UI autorizada del portal y devuelve la pestaña autenticada.
// Ningún login se adivina, ni se extraen contraseñas; máximo una renovación por fuente.
export async function runLabs(tab, options, secrets = {}) {
  let tabs = tab && typeof tab.url === 'function' ? {exalab:tab, eloisa:tab} : {...(tab || {})};
  const attempts = new Set();
  const rounds = [];
  let current = {...options};
  while (true) {
    const result = await runOnce(tabs, current, secrets);
    rounds.push({code:result.code, timedOut:result.timedOut});
    const line = result.stdout.split('\n').findLast(line => line.startsWith('CLINICAL_RESULT '));
    let summary;
    try { summary = line ? JSON.parse(line.slice('CLINICAL_RESULT '.length)) : null; } catch {}
    if (result.timedOut || !summary || typeof options.reauthenticate !== 'function') return {...result, rounds, recovery:summary};
    const renewed = [];
    for (const source of summary.auth_sources || []) {
      if (!['eloisa','exalab','rayen'].includes(source) || attempts.has(source)) continue;
      attempts.add(source);
      try {
        const replacement = await options.reauthenticate(source, tabs[source]);
        if (replacement) { tabs[source] = replacement; renewed.push(source); }
      } catch { /* Intervención pendiente; conservar avance y resultados. */ }
    }
    if (!renewed.length) return {...result, rounds, recovery:summary};
    current = {...current, resume:summary.checkpoint, fresh:false, retrySources:renewed.join(',')};
  }
}

async function collectSessions(tab, options, secrets) {
  const payload = {};
  const sources = ['syslab', 'exalab', 'eloisa', 'mmrad', 'his', 'rayen', 'email'];
  const selected = options.source === 'both' ? ['syslab', 'exalab'] : options.source === 'all' ? sources.filter(s => s !== 'email') : options.source.split(',');
  if (!selected.length || new Set(selected).size !== selected.length || selected.some(s => !sources.includes(s))) throw new Error('Fuentes inválidas.');
  const tabs = tab && typeof tab.url === 'function' ? { exalab: tab, eloisa: tab } : (tab || {});
  if (secrets.syslab && selected.includes('syslab')) payload.syslab = secrets.syslab;
  if (secrets.mmrad && selected.includes('mmrad')) payload.mmrad = secrets.mmrad;
  if (secrets.his && selected.includes('his')) payload.his = secrets.his;
  if (selected.includes('exalab')) {
    let ready = false;
    try { if (tabs.exalab) {
      const url = new URL(await tabs.exalab.url());
      ready = url.origin === 'https://exalab.saludoriente.cl' && url.pathname.startsWith('/web_ssmo/');
      if (ready) {
        const cdp = await tabs.exalab.capabilities.get('cdp');
        const session = await cdp.send('Network.getCookies', { urls: ['https://exalab.saludoriente.cl/web_ssmo/index.php'] });
        const agent = await cdp.send('Runtime.evaluate', { expression: 'navigator.userAgent', returnByValue: true });
        payload.exalab = { cookies: session.cookies.filter(c => ['PHPSESSID', 'cf_clearance'].includes(c.name)), user_agent: agent.result.value };
      }
    } } catch { /* Python informa sesión pendiente para esta fuente. */ }

  }
  if (selected.includes('eloisa')) {
    let ready = false;
    try { if (tabs.eloisa) {
      const url = new URL(await tabs.eloisa.url());
      ready = url.origin === 'https://clinicohangaroa.eloisa.cl' && url.pathname.startsWith('/main');
      if (ready) {
        const cdp = await tabs.eloisa.capabilities.get('cdp');
        const response = await cdp.send('Runtime.evaluate', {
          expression: "(()=>{try{return JSON.parse(localStorage.getItem('userSession')||'{}').accessToken||null}catch{return null}})()",
          returnByValue: true
        });
        const accessToken = response?.result?.value;
        ready = typeof accessToken === 'string' && !!accessToken;
        if (ready && accessToken.split('.').length === 3) {
          try { const claims = JSON.parse(Buffer.from(accessToken.split('.')[1], 'base64url').toString());
            if (typeof claims.exp === 'number' && claims.exp * 1000 <= Date.now()) ready = false;
          } catch { /* Token opaco: la primera lectura autenticada comprueba vigencia. */ }
        }
        if (ready) payload.eloisa = { access_token: accessToken };
      }
    } } catch { /* Continúan las fuentes independientes. */ }

  }
  if (selected.includes('rayen') && tabs.rayen) {
    try {
      const url = new URL(await tabs.rayen.url());
      if (url.origin === 'https://fichamedico.rayensalud.cl' && url.pathname.startsWith('/dashboard/')) {
        const cdp = await tabs.rayen.capabilities.get('cdp');
        const response = await cdp.send('Runtime.evaluate', {
          expression: `(async()=>{const r=await fetch('/api/auth/session',{method:'GET',cache:'no-store'});if(!r.ok)return null;const j=await r.json();return j.ok&&j.session?.token?{token:j.session.token,facilityId:j.session.facilityId}:null;})()`,
          awaitPromise: true, returnByValue: true,
        });
        const session = response.result?.value;
        if (typeof session?.token === 'string' && Number.isInteger(session.facilityId) && session.facilityId > 0) payload.rayen = session;
      }
    } catch { /* No se bloquean las otras fuentes si esta pestaña desaparece. */ }
  }
  return {payload, selected};
}

async function currentUid() {
  if (typeof process !== 'undefined' && typeof process.getuid === 'function') return process.getuid();
  // Some embedded runtimes expose child_process but no process global.
  return await new Promise((resolve,reject) => {
    const child=spawn('/usr/bin/id',['-u'],{stdio:['ignore','pipe','ignore']});
    let value='';const timer=setTimeout(()=>{child.kill();reject(new Error('No se pudo comprobar el propietario.'));},2000);
    child.stdout.on('data',chunk=>{value+=chunk;if(value.length>32)child.kill();});
    child.on('error',()=>{clearTimeout(timer);reject(new Error('No se pudo comprobar el propietario.'));});
    child.on('close',code=>{clearTimeout(timer);if(code===0 && /^\d+\s*$/.test(value))resolve(Number(value.trim()));else reject(new Error('Propietario no verificable.'));});
  });
}

export async function writeLabsSession(tabs, options, pipe, secrets = {}) {
  const uid=await currentUid();
  const info = await lstat(pipe);
  const parent = await lstat(dirname(pipe));
  if (!info.isFIFO() || info.isSymbolicLink() || info.uid !== uid || (info.mode & 0o077) ||
      !parent.isDirectory() || parent.isSymbolicLink() || parent.uid !== uid || (parent.mode & 0o077)) {
    throw new Error('Se requiere una FIFO privada del usuario dentro de un directorio privado.');
  }
  const {payload, selected} = await collectSessions(tabs, options, secrets);
  const handle = await open(pipe, constants.O_WRONLY | constants.O_NONBLOCK | constants.O_NOFOLLOW);
  try {
    const actual = await handle.stat();
    if (!actual.isFIFO() || actual.ino !== info.ino || actual.dev !== info.dev) throw new Error('La tubería cambió.');
    const bytes = Buffer.from(JSON.stringify(payload));
    if (bytes.length > 65536) throw new Error('Sesión demasiado grande.');
    let sent=0;
    while (sent < bytes.length) { const {bytesWritten}=await handle.write(bytes, sent, bytes.length-sent); sent+=bytesWritten; }
    bytes.fill(0);
    return {selected, sessions:Object.keys(payload)};
  } finally { await handle.close(); }
}
