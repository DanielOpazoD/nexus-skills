import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

// Se llama desde cua_repl con una pestaña Exalab autenticada del perfil personal.
// Las cookies viajan solo por stdin al proceso local, sin archivos ni argumentos.
export async function runExalab(tab, options) {
  // Sin límite total por defecto; Python mantiene sus tiempos de espera de red.
  const timeoutMs = options.timeoutMs ?? 0;
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 0 || timeoutMs > 2147483647) {
    throw new Error('timeoutMs debe ser un entero entre 0 (sin límite total) y 2147483647.');
  }
  const url = new URL(await tab.url());
  if (url.origin !== 'https://exalab.saludoriente.cl' || !url.pathname.startsWith('/web_ssmo/')) {
    throw new Error('Primero inicia sesión en Exalab con ClaveÚnica en el perfil personal de Chrome.');
  }
  const cdp = await tab.capabilities.get('cdp');
  const result = await cdp.send('Network.getCookies', { urls: ['https://exalab.saludoriente.cl/web_ssmo/index.php'] });
  const agent = await cdp.send('Runtime.evaluate', { expression: 'navigator.userAgent', returnByValue: true });
  const cookies = result.cookies.filter(c => ['PHPSESSID', 'cf_clearance'].includes(c.name));
  const payload = JSON.stringify({ cookies, user_agent: agent.result.value });
  const script = options.script || fileURLToPath(new URL('./exalab_download.py', import.meta.url));
  const args = [script, '--session-stdin', '--rut', options.rut, '--period', options.period, '--output', options.output];
  if (options.asOf) args.push('--as-of', options.asOf);
  if (options.listOnly) args.push('--list-only');
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
    child.stdin.end(payload);
  });
}
