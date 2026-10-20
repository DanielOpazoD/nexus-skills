/* Carpeta Pacientes autorizada por el usuario. Sólo se persiste su handle. */
(function(root){
  'use strict';
  const C=root.NexoLibraryCore,R=root.ClinicalCatalog.library;
  function database(){return new Promise((resolve,reject)=>{
    const request=indexedDB.open('nexo-connections',1);
    request.onupgradeneeded=()=>request.result.createObjectStore('handles');
    request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(Error('No se pudo recordar la carpeta.'));request.onblocked=()=>reject(Error('Cierra las otras ventanas de Nexo y vuelve a intentar.'));
  });}
  async function savedHandle(value){
    const db=await database();
    try{return await new Promise((resolve,reject)=>{
      const transaction=db.transaction('handles',value===undefined?'readonly':'readwrite'),store=transaction.objectStore('handles');
      const request=value===undefined?store.get('patients'):value===null?store.delete('patients'):store.put(value,'patients');
      let result;request.onsuccess=()=>{result=request.result;};
      transaction.oncomplete=()=>resolve(result);transaction.onerror=()=>reject(Error('No se pudo guardar la conexión.'));
    });}finally{db.close();}
  }
  async function file(directory,name,max){return C.textFile(await directory.getFileHandle(name),max);}
  async function folder(directory,name){return directory.getDirectoryHandle(name);}
  async function folderIdentity(directory){
    const bases=[];
    try{bases.push(await folder(directory,R.controlFolder));}catch(error){if(error.name!=='NotFoundError')throw error;}
    bases.push(directory);
    for(const base of bases){try{return C.identity((await file(base,R.identityFilename,4096)).text);}catch(error){if(error.name!=='NotFoundError')throw error;}}
    const identities=[];
    for(const base of bases){
      let count=0;
      for await(const [name,handle] of base.entries()){
        if(handle.kind!=='file'||! /^(Estado de descargas|Resumen de fuentes) - .+\.txt$/.test(name))continue;
        if(++count>200)break;
        try{identities.push(C.identity((await C.textFile(handle,16384)).text));}catch(_){/* Controles sin encabezado completo no acreditan identidad. */}
      }
    }
    const first=identities[0];
    if(!first||identities.some(item=>item.rut!==first.rut||!C.sameName(item.name,first.name)))throw Error('Identidad ambigua o ausente.');
    return first;
  }
  async function currentDelivery(directory){
    try{
      const control=await folder(directory,R.controlFolder);
      const manifest=JSON.parse((await file(control,R.manifestFilename,1048576)).text);
      if(manifest.version!==1)throw Error('Índice no compatible.');
      const current=manifest.products?.['delivery-antecedentes']?.current||null;
      if(current){
        const name=typeof current.path==='string'&&current.path.startsWith(R.readingFolder+'/')?current.path.slice(R.readingFolder.length+1):'';
        if(!name||/[\\/]/.test(name)||C.filenameDate(name)===null||!/^[a-f0-9]{64}$/.test(current.sha256))throw Error('Entrega no verificable.');
      }
      return current;
    }catch(error){if(error.name==='NotFoundError')return null;throw error;}
  }
  class DriveLibrary{
    constructor(handle){if(handle?.kind!=='directory'||handle.name!==R.patientsFolder)throw Error('Selecciona la carpeta «Pacientes».');this.handle=handle;this.references=new Map();this.patientFolders=new Map();}
    async list(){
      if(await this.handle.queryPermission({mode:'read'})!=='granted')throw Object.assign(Error('Vuelve a conectar tu carpeta Pacientes.'),{code:'permission'});
      const patients=[],references=new Map(),folders=new Map();let issues=0;
      for await(const [directoryName,handle] of this.handle.entries()){
        if(handle.kind!=='directory' || directoryName.startsWith('.'))continue;
        if(patients.length>=R.maxPatients){issues++;break;}
        try{
          const patient=await folderIdentity(handle);let control;
          try{control=await folder(handle,R.controlFolder);}catch(error){if(error.name!=='NotFoundError')throw error;}
          if(!C.sameName(directoryName.replace(/ \(\d+\)$/,''),patient.name))throw Error('Nombre contradictorio.');
          const current=await currentDelivery(handle);
          const documents=[];
          let folderUrl=null;
          if(control){try{folderUrl=C.folderUrl(JSON.parse((await file(control,'Carpeta Drive.json',4096)).text),patient);}catch(error){if(error.name!=='NotFoundError')issues++;}}
          try{
            const reading=await folder(handle,R.readingFolder);
            const candidates=current?[[current.path.slice(R.readingFolder.length+1),await reading.getFileHandle(current.path.slice(R.readingFolder.length+1))]]:reading.entries();
            for await(const [name,document] of candidates){
              if(document.kind!=='file')continue;
              try{
                const date=C.filenameDate(name);if(date===null)continue;
                if(documents.length>=R.maxDocuments){issues++;break;}
                const content=await C.textFile(document),found=C.documentIdentity(content.text,patient.name);
                if(found.rut!==patient.rut || !C.sameName(found.name,patient.name))throw Error('Identidad contradictoria.');
                if(current && (current.path!==R.readingFolder+'/'+name || current.sha256!==content.sha256))continue;
                const status=current?.freshness|| (current?'current':'existing');
                const id=await C.checksum(new TextEncoder().encode(patient.rut+'\0'+directoryName+'\0'+name+'\0'+content.sha256));
                documents.push({id,date,referenceDate:C.referenceDate(content.text),status,sha256:content.sha256});
                references.set(id,{directoryName,filename:name,...patient,status,sha256:content.sha256,tracked:!!current});
              }catch(_){issues++;}
            }
          }catch(error){if(error.name!=='NotFoundError')throw error;}
          if(current && !documents.length)issues++;
          const id=await C.checksum(new TextEncoder().encode(patient.rut+'\0'+directoryName));
          folders.set(id,directoryName);patients.push({id,...patient,documents,folderUrl});
        }catch(_){issues++;}
      }
      const counts=new Map();for(const patient of patients)counts.set(patient.rut,(counts.get(patient.rut)||0)+1);
      const valid=patients.filter(patient=>counts.get(patient.rut)===1);
      issues+=patients.length-valid.length;
      const ids=new Set(valid.flatMap(p=>p.documents.map(d=>d.id)));
      this.references=new Map([...references].filter(([id])=>ids.has(id)));
      this.patientFolders=new Map(valid.map(patient=>[patient.id,folders.get(patient.id)]));
      return {version:1,available:true,patients:valid,issues};
    }
    async patient(id){
      const directoryName=this.patientFolders.get(id),root=this.handle;
      if(!directoryName)throw Error('Expediente no disponible. Actualiza la lista.');
      // El mismo contrato de listado, limitado al expediente ya identificado.
      const scoped={kind:'directory',name:R.patientsFolder,
        queryPermission:options=>root.queryPermission(options),
        getDirectoryHandle:name=>root.getDirectoryHandle(name),
        async *entries(){yield [directoryName,await root.getDirectoryHandle(directoryName)];}};
      const library=new DriveLibrary(scoped),catalog=await library.list();
      const patient=catalog.patients.find(patient=>patient.id===id);
      if(!patient)throw Error('Expediente pendiente de revisión.');
      for(const [key,reference] of this.references)if(reference.directoryName===directoryName)this.references.delete(key);
      for(const [key,reference] of library.references)this.references.set(key,reference);
      return patient;
    }
    async read(id,sha256){
      // Resolver la ruta otra vez: un handle antiguo no acredita un archivo movido.
      if(await this.handle.queryPermission({mode:'read'})!=='granted')throw Object.assign(Error('Vuelve a conectar tu carpeta Pacientes.'),{code:'permission'});
      const reference=this.references.get(id);
      if(!reference || reference.sha256!==sha256)throw Error('El resumen cambió. Actualiza la lista.');
      const directory=await folder(this.handle,reference.directoryName),patient=await folderIdentity(directory);
      if(patient.rut!==reference.rut || !C.sameName(patient.name,reference.name))throw Error('La identidad del expediente cambió.');
      const current=await currentDelivery(directory);
      if((reference.tracked&&!current) || current&&(current.path!==R.readingFolder+'/'+reference.filename || current.sha256!==sha256))throw Error('El resumen cambió. Actualiza la lista.');
      const reading=await folder(directory,R.readingFolder);
      const content=await C.textFile(await reading.getFileHandle(reference.filename)),identity=C.documentIdentity(content.text,reference.name);
      if(content.sha256!==sha256 || identity.rut!==reference.rut || !C.sameName(identity.name,reference.name))throw Error('El resumen cambió durante la lectura.');
      if(JSON.stringify(current)!==JSON.stringify(await currentDelivery(directory)))throw Error('El resumen cambió durante la lectura.');
      const status=current?.freshness||(current?'current':'existing');
      return {id,...content,name:reference.name,rut:reference.rut,status};
    }
  }
  root.NexoDriveLibrary={DriveLibrary,savedHandle};
})(globalThis);
