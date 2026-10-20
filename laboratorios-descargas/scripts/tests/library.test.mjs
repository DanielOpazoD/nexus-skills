import test from 'node:test';import assert from 'node:assert/strict';import vm from 'node:vm';
import {readFile} from 'node:fs/promises';import {webcrypto} from 'node:crypto';
const base=new URL('../../',import.meta.url);
const catalog=JSON.parse(await readFile(new URL('assets/clinical_catalog.json',base),'utf8'));
const core=await readFile(new URL('chrome-bridge/panel/library_core.js',base),'utf8');
const drive=await readFile(new URL('chrome-bridge/panel/library_drive.js',base),'utf8');
const cases=JSON.parse(await readFile(new URL('library_cases.json',import.meta.url),'utf8'));
function setup(){const ctx={ClinicalCatalog:catalog,crypto:webcrypto,TextEncoder,TextDecoder,Uint8Array,Date,Map,Set};vm.createContext(ctx);vm.runInContext(core+'\n'+drive,ctx);return ctx;}
const text='Paciente: Paciente Ficticio\nRUT: 11111111-1\nFecha de referencia: 19-10-2026\n\nAntecedentes documentados.';
function file(name,content){return {kind:'file',name,content,async getFile(){const bytes=new TextEncoder().encode(this.content);return {size:bytes.length,arrayBuffer:async()=>bytes.buffer};}};}
function directory(name,children={}){return {kind:'directory',name,children,permission:'granted',async queryPermission(){return this.permission;},async getFileHandle(key){if(this.children[key]?.kind!=='file')throw Object.assign(Error('missing'),{name:'NotFoundError'});return this.children[key];},async getDirectoryHandle(key){if(this.children[key]?.kind!=='directory')throw Object.assign(Error('missing'),{name:'NotFoundError'});return this.children[key];},async *entries(){yield*Object.entries(this.children);}};}
function patient(name='Paciente Ficticio',rut='11111111-1'){
 const report=file('Resumen de antecedentes.txt',text.replace('Paciente Ficticio',name).replace('11111111-1',rut));
 return directory(name,{'Control y trazabilidad':directory('Control y trazabilidad',{'Identidad del paciente.txt':file('Identidad del paciente.txt',`Paciente: ${name}\nRUT: ${rut}\n`)}),'Lectura y entregas':directory('Lectura y entregas',{'Resumen de antecedentes.txt':report})});
}
test('Python y JavaScript comparten los casos de identidad y nombres clínicos',()=>{
 const C=setup().NexoLibraryCore;
 for(const c of cases.identities){let valid=false;try{const found=C.documentIdentity(c.text,c.name);valid=found.rut===c.rut&&C.sameName(found.name,c.name);}catch(_){}assert.equal(valid,c.valid);}
 for(const c of cases.filenames)assert.equal(C.filenameDate(c.name),c.date);
 for(const date of ['31-02-2026','1-10-2026','20/10/2026'])assert.throws(()=>C.date(date));
 assert.equal(C.matches({name:'Ángela Pérez Soto',rut:'11111111-1'},'angela perez'),true);
});
test('Drive lee sólo resúmenes del paciente y rechaza bytes cambiados',async()=>{
 const {NexoDriveLibrary:D}=setup(),p=patient(),root=directory('Pacientes',{'Paciente Ficticio':p});
 const library=new D.DriveLibrary(root),catalog=await library.list(),doc=catalog.patients[0].documents[0];
 assert.equal((await library.read(doc.id,doc.sha256)).text,text);
 p.children['Lectura y entregas'].children['Resumen de antecedentes.txt'].content+='Cambio';
 await assert.rejects(library.read(doc.id,doc.sha256),/cambió/);
 assert.throws(()=>new D.DriveLibrary(directory('Descargas')),/Pacientes/);
 root.permission='denied';await assert.rejects(library.list(),/conectar/);
});
test('registro vigente, versión histórica y bloqueo por actualización pendiente',async()=>{
 const {NexoDriveLibrary:D,NexoLibraryCore:C}=setup(),p=patient();
 const current=p.children['Lectura y entregas'].children['Resumen de antecedentes.txt'];
 p.children['Lectura y entregas'].children['19-10-2026 Resumen antecedentes.txt']=file('19-10-2026 Resumen antecedentes.txt',text);
 const sha=await C.checksum(new TextEncoder().encode(current.content));
 p.children['Control y trazabilidad'].children['Entregas vigentes.json']=file('Entregas vigentes.json',JSON.stringify({version:1,products:{'delivery-antecedentes':{current:{path:'Lectura y entregas/Resumen de antecedentes.txt',sha256:sha,freshness:'stale'}}}}));
 const docs=(await new D.DriveLibrary(directory('Pacientes',{'Paciente Ficticio':p})).list()).patients[0].documents;
 assert.equal(docs.length,1);assert.equal(C.canCopy(docs[0]),false);
});
test('homónimos separados; RUT duplicado y encabezado bajo otro rol quedan fuera',async()=>{
 const {NexoDriveLibrary:D}=setup(),p=patient(),two=patient('Paciente Ficticio','22222222-2');
 const root=directory('Pacientes',{'Paciente Ficticio':p,'Paciente Ficticio (2)':two});
 assert.equal((await new D.DriveLibrary(root).list()).patients.length,2);
 root.children['Paciente Ficticio (3)']=patient();
 assert.equal((await new D.DriveLibrary(root).list()).patients.length,1);
 two.children['Lectura y entregas'].children['Resumen de antecedentes.txt'].content='Paciente: Otra Persona\nRUT: 11111111-1\nMédico: Paciente Ficticio\nRUT: 22222222-2';
 assert.equal((await new D.DriveLibrary(root).list()).patients[0].documents.length,0);
});
test('controles antiguos identifican sin depender de un archivo nuevo',async()=>{
 const {NexoDriveLibrary:D}=setup(),p=patient(),control=p.children['Control y trazabilidad'];
 delete control.children['Identidad del paciente.txt'];control.children['Estado de descargas - 19-10-2026.txt']=file('Estado de descargas - 19-10-2026.txt','Paciente: Paciente Ficticio\nRUT: 11111111-1\n');
 assert.equal((await new D.DriveLibrary(directory('Pacientes',{'Paciente Ficticio':p})).list()).patients[0].documents.length,1);
 control.children['Estado de descargas - 20-10-2026.txt']=file('Estado de descargas - 20-10-2026.txt','Paciente: Paciente Ficticio\nRUT: 22222222-2\n');
 assert.equal((await new D.DriveLibrary(directory('Pacientes',{'Paciente Ficticio':p})).list()).patients.length,0);
});
test('el enlace de Drive exige identidad y un ID de carpeta válido, sin URL libre',async()=>{
 const {NexoLibraryCore:C,NexoDriveLibrary:D}=setup(),p=patient();
 const link={version:1,rut:'11111111-1',name:'Paciente Ficticio',folderId:'folder-fixture-123'};
 assert.equal(C.folderUrl(link,{rut:'11111111-1',name:'Paciente Ficticio'}),'https://drive.google.com/drive/folders/folder-fixture-123');
 for(const change of [{rut:'22222222-2'},{folderId:'https://evil.invalid/'},{name:'Otra Persona'}])assert.throws(()=>C.folderUrl({...link,...change},{rut:'11111111-1',name:'Paciente Ficticio'}));
 p.children['Control y trazabilidad'].children['Carpeta Drive.json']=file('Carpeta Drive.json',JSON.stringify(link));
 assert.match((await new D.DriveLibrary(directory('Pacientes',{'Paciente Ficticio':p})).list()).patients[0].folderUrl,/^https:\/\/drive.google.com\/drive\/folders\//);
});
