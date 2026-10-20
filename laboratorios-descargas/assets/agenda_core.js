/* Contrato de agenda: selección determinista, sin almacenamiento ni ejecución de descargas. */
(function (root) {
  'use strict';
  const ORIGIN = 'https://clinicohangaroa.eloisa.cl';
  function day(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) throw Error('Selecciona una fecha válida.');
    const parsed = new Date(value + 'T12:00:00Z');
    if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0,10) !== value) throw Error('Selecciona una fecha válida.');
    return value;
  }
  function id(value) {
    return (typeof value === 'number' || typeof value === 'string') && /^\d{1,12}$/.test(String(value)) && Number.isSafeInteger(Number(value)) && Number(value) > 0 ? Number(value) : null;
  }
  function rut(value) {
    if (typeof value !== 'string' && typeof value !== 'number') throw Error('RUT inválido.');
    const raw = String(value).trim().replaceAll('.','').toUpperCase();
    if (!/^\d{7,8}-?[0-9K]$/.test(raw)) throw Error('RUT inválido.');
    const clean = raw.replace('-',''), body = clean.slice(0,-1), digit = clean.slice(-1);
    const check = 11 - [...body].reverse().reduce((sum,n,i) => sum + Number(n) * (2 + i % 6),0) % 11;
    if (digit !== (check === 11 ? '0' : check === 10 ? 'K' : String(check))) throw Error('RUT inválido.');
    return body + '-' + digit;
  }
  function context(session) {
    // Sólo claves de identidad explícitas; jamás adoptar el primer id genérico.
    const matches = {officer:[],node:[]};
    const queue = [{value:session,depth:0}];
    while (queue.length) {
      const {value,depth} = queue.shift();
      if (!value || typeof value !== 'object' || Array.isArray(value) || depth > 4) continue;
      for (const [key,item] of Object.entries(value)) {
        if (/token|password|clave|secret|refresh/i.test(key)) continue;
        if (item && typeof item === 'object') { queue.push({value:item,depth:depth+1});continue; }
        const number = id(item);
        if (!number) continue;
        if (/^id(funcionario(prestador)?|prestador|profesional)$|^(funcionario|prestador|profesional)id$/i.test(key)) matches.officer.push({depth,number});
        if (/^idnodo$|^nodoid$/i.test(key)) matches.node.push({depth,number});
      }
    }
    function unique(items) {
      if (!items.length) return null;
      const shallow = Math.min(...items.map(item=>item.depth));
      const values = [...new Set(items.filter(item=>item.depth===shallow).map(item=>item.number))];
      return values.length===1 ? values[0] : null;
    }
    const officerId = unique(matches.officer), nodeId = unique(matches.node);
    if (!officerId || nodeId !== 5576) throw Error('No se pudo identificar tu agenda de Hanga Roa. Abre tu sesión de Eloísa y vuelve a cargar.');
    return {officerId,nodeId};
  }
  function url(date, identity) {
    const date8 = day(date).replaceAll('-','');
    if (!id(identity?.officerId) || identity.nodeId !== 5576) throw Error('Agenda no identificada.');
    const pairs = [['FechaHoraInicio',date8+' 000000'],['FechaHoraTermino',date8+' 235959'],
      ['IdsDeRecursos',identity.officerId],['EsAnulado',2],['EsGrupal',2],
      ['TraerLlamadosPaciente',true],['TraerTeleconsulta',true]];
    return ORIGIN+'/API/api/rayen/Citas/ListaPacientesCitados/'+identity.nodeId+'/'+pairs.map(([key,value])=>key+'='+encodeURIComponent(String(value))).join(';');
  }
  function nameKey(value) { return value.normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/\s+/g,' ').trim().toLowerCase(); }
  function normalize(rows, date, identity) {
    url(date,identity);
    if (!Array.isArray(rows) || rows.length > 5000) throw Error('Eloísa no devolvió una agenda reconocible.');
    const groups = new Map(), appointments = new Map(), conflicts = new Set();
    let rejected = 0;
    for (const row of rows) {
      try {
        if (!row || typeof row !== 'object') throw Error();
        const patient = row.UsuarioAps, patientRut = rut(patient?.Rut ?? patient?.Run);
        const patientId = id(patient?.Id), appointmentId = id(row.Id);
        const name = typeof patient?.NombreFormateado === 'string' ? patient.NombreFormateado.trim() : '';
        const when = String(row.FechaHoraInicio || ''), match = /^(\d{8}) ([0-2]\d)([0-5]\d)(?:[0-5]\d)?$/.exec(when);
        if (!patientId || !appointmentId || name.length < 2 || name.length > 200 || !match || Number(match[2]) > 23 || match[1] !== date.replaceAll('-','')) throw Error();
        // Citas grupales necesitan expansión explícita; nunca tomar sólo el primer paciente.
        if (row.EsGrupal === true || row.EsGrupal === 1) throw Error();
        if (row.IdNodo !== undefined && id(row.IdNodo) !== identity.nodeId) throw Error();
        if (row.IdFuncionarioPrestador !== undefined && id(row.IdFuncionarioPrestador) !== identity.officerId) throw Error();
        if (row.Nodo?.Id !== undefined && id(row.Nodo.Id) !== identity.nodeId) throw Error();
        if (row.FuncionarioPrestador?.Id !== undefined && id(row.FuncionarioPrestador.Id) !== identity.officerId) throw Error();
        const state = typeof row.Tag?.Nombre === 'string' ? row.Tag.Nombre.slice(0,100) : '';
        const flagged = value => value === true || value === 1;
        const cancelled = [row.EsAnulado,row.EsBorrado,row.Tag?.EsAnulado,row.Tag?.EsBorrado,row.Tag?.EsBloqueado].some(flagged) || /anulad|cancelad|suspendid/i.test(state);
        const fingerprint = JSON.stringify([patientRut,patientId,nameKey(name),when,state,cancelled]);
        const prior = appointments.get(appointmentId);
        if (prior && prior.fingerprint !== fingerprint) { conflicts.add(prior.rut);conflicts.add(patientRut); }
        appointments.set(appointmentId,{rut:patientRut,fingerprint});
        let group = groups.get(patientRut);
        if (!group) { group = {rut:patientRut,name,patientId,times:[],states:[],appointmentIds:[],selectable:false};groups.set(patientRut,group); }
        if (group.patientId !== patientId || nameKey(group.name) !== nameKey(name)) conflicts.add(patientRut);
        if (!group.appointmentIds.includes(appointmentId)) {
          group.appointmentIds.push(appointmentId);group.times.push(match[2]+':'+match[3]);
          if (state && !group.states.includes(state)) group.states.push(state);
          if (cancelled && !state) group.states.push('No disponible');
        }
        if (!cancelled) group.selectable = true;
      } catch (_) { rejected += 1; }
    }
    for (const key of conflicts) {
      const group = groups.get(key);
      if (group) { group.selectable = false;group.states = ['Identidad inconsistente; revisar en Eloísa']; }
    }
    const patients = [...groups.values()].map(({patientId,...group})=>({...group,times:[...new Set(group.times)].sort()}));
    patients.sort((a,b)=>(a.times[0]+a.name).localeCompare(b.times[0]+b.name));
    return {date,identity,patients,rejected,conflicts:conflicts.size,status:rejected || conflicts.size ? 'partial' : 'complete'};
  }
  root.ClinicalAgenda = {day,id,rut,context,url,normalize};
})(globalThis);
