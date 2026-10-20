/* Consultas de lectura desde el equipo donde está abierta esta extensión. */
async function readAgenda(message) {
  if (Object.keys(message).some(key=>!['type','id','date'].includes(key)) ||
      typeof message.id !== 'string' || !/^[a-f0-9]{32}$/.test(message.id)) throw Error('Solicitud de agenda inválida.');
  ClinicalAgenda.day(message.date);
  const tab = await validTab('https://clinicohangaroa.eloisa.cl/main*','https://clinicohangaroa.eloisa.cl','/main');
  const [read] = await chrome.scripting.executeScript({target:{tabId:tab.id},func:() => {
    try {
      const session = JSON.parse(localStorage.getItem('userSession') || '{}');
      // Extraer sólo claves de contexto. El resto de la sesión no sale de esta función.
      function metadata(value,depth=0) {
        if (!value || typeof value !== 'object' || Array.isArray(value) || depth > 4) return null;
        const out = {};
        for (const [key,item] of Object.entries(value)) {
          if (/token|password|clave|secret|refresh/i.test(key)) continue;
          // La sesión real serializa estos dos objetos como JSON de texto.
          if (['nodo','funcionarioprestador'].includes(key.toLowerCase())) {
            try {
              const entity = typeof item === 'string' ? JSON.parse(item) : item;
              out[key] = {[key.toLowerCase()==='nodo' ? 'IdNodo' : 'IdFuncionarioPrestador']:entity?.id ?? entity?.Id};
            } catch (_) { out[key] = null; }
            continue;
          }
          if (item && typeof item === 'object') out[key] = metadata(item,depth+1);
          else if (/^id(funcionario(prestador)?|prestador|profesional|nodo)$|^(funcionario|prestador|profesional|nodo)id$/i.test(key)) out[key] = item;
        }
        return out;
      }
      return {token:session.accessToken,context:metadata(session)};
    } catch (_) { return null; }
  }});
  const session = read?.result;
  if (typeof session?.token !== 'string' || !session.token) throw Error('Inicia sesión en Eloísa en este perfil de Chrome.');
  try {
    const identity = ClinicalAgenda.context(session.context);
    const response = await fetch(ClinicalAgenda.url(message.date,identity),{
      method:'GET',headers:{Authorization:'Bearer '+session.token,Accept:'application/json'},
      credentials:'omit',redirect:'error',cache:'no-store',signal:AbortSignal.timeout(20000)});
    if ([401,403].includes(response.status)) throw Error('Sesión de Eloísa vencida. Vuelve a iniciar sesión y carga la agenda.');
    if (!response.ok) throw Error('Eloísa no respondió. Conserva la selección y vuelve a cargar la agenda.');
    if (!/json/i.test(response.headers.get('content-type') || '')) throw Error('Eloísa no devolvió la agenda. Comprueba tu sesión.');
    const reader = response.body.getReader(), chunks = [];
    let size = 0;
    while (true) {
      const {value,done} = await reader.read();
      if (done) break;
      size += value.length;
      if (size > 4*1024*1024) { await reader.cancel();throw Error('La agenda excede el tamaño admitido; no se importó.'); }
      chunks.push(value);
    }
    const bytes = new Uint8Array(size);let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk,offset);offset += chunk.length; }
    const rows = JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
    return ClinicalAgenda.normalize(rows,message.date,identity);
  } finally { session.token = null; }
}
