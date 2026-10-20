/* Contrato de lectura; sin DOM, red, almacenamiento ni datos de pacientes fijos. */
(function(root){
  'use strict';
  function normalize(value){return value.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('es').replace(/[^a-z0-9]/g,'');}
  function sameName(a,b){const tokens=value=>value.split(/\s+/).map(normalize).sort().join('|');return tokens(a)===tokens(b);}
  function rut(value){
    const clean=String(value).replace(/[.\s]/g,'').toUpperCase();
    const {minDigits,maxDigits}=root.ClinicalCatalog.identity;
    if(!new RegExp(`^\\d{${minDigits},${maxDigits}}-[0-9K]$`).test(clean))throw Error('Identidad no válida.');
    const [body,digit]=clean.split('-');let sum=0;
    [...body].reverse().forEach((n,i)=>{sum+=Number(n)*(2+i%6);});
    const check=11-sum%11;
    if(digit!==(check===11?'0':check===10?'K':String(check)))throw Error('Identidad no válida.');
    return clean;
  }
  function date(value){
    if(!/^\d{2}-\d{2}-\d{4}$/.test(value))throw Error('Fecha no válida.');
    const [d,m,y]=value.split('-').map(Number),day=new Date(Date.UTC(y,m-1,d));
    if(day.getUTCFullYear()!==y || day.getUTCMonth()!==m-1 || day.getUTCDate()!==d)throw Error('Fecha no válida.');
    return value;
  }
  function identity(text){
    const header=text.slice(0,2000).replace(/\r\n/g,'\n');
    const match=header.match(/^Paciente:\s*([^\n]+)\n(?:RUT|RUN):\s*([\d.]+\s*-\s*[\dKk])\s*$/mi);
    if(!match || (header.match(/^Paciente:/gmi)||[]).length!==1)throw Error('Identidad del encabezado pendiente.');
    return {name:match[1].trim(),rut:rut(match[2])};
  }
  function documentIdentity(text,expectedName){
    try{return identity(text);}catch(_){
      const lines=text.replace(/\r\n/g,'\n').split('\n');
      if(lines.length<2||!sameName(lines[0].trim(),expectedName))throw Error('Nombre del encabezado no coincide.');
      const match=lines[1].trim().match(/^(?:RUT|RUN)\s*:?\s*([\d.]+\s*-\s*[\dKk])$/i);
      if(!match)throw Error('RUT del encabezado ausente.');
      return {name:lines[0].trim(),rut:rut(match[1])};
    }
  }
  function filenameDate(name){
    for(const pattern of root.ClinicalCatalog.library.filenamePatterns){
      const match=name.match(new RegExp(pattern,'i'));if(match)return match[1]?date(match[1]):'';
    }
    return null;
  }
  function referenceDate(text){const match=text.slice(0,2000).match(/^Fecha de referencia:\s*(\d{2}-\d{2}-\d{4})\s*$/m);return match?date(match[1]):'';}
  async function checksum(raw){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',raw))].map(x=>x.toString(16).padStart(2,'0')).join('');}
  async function textFile(handle,maximum=root.ClinicalCatalog.library.maxTextBytes){
    const file=await handle.getFile();if(file.size>maximum)throw Error('Documento demasiado grande.');
    const bytes=await file.arrayBuffer(),text=new TextDecoder('utf-8',{fatal:true}).decode(bytes).replace(/\r\n/g,'\n');
    if(text.includes('\0'))throw Error('Texto no válido.');
    return {text,sha256:await checksum(bytes)};
  }
  function matches(patient,query){const term=normalize(query);return !term || normalize(patient.name).includes(term) || normalize(patient.rut).includes(term);}
  function canCopy(document){return !!document && ['current','existing'].includes(document.status);}
  root.NexoLibraryCore={normalize,sameName,rut,date,identity,documentIdentity,filenameDate,referenceDate,checksum,textFile,matches,canCopy};
})(globalThis);
