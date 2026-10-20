"""Cola local persistente. Sesiones y contraseñas existen solo en memoria/llavero."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import copy
import fcntl
import json
import os
import secrets
import signal
import subprocess
import threading
import time
from clinical_archive import PatientArchive, DriveVerifier, DEFAULT_ROOT
from clinical_store import QueueStore
from drive_oauth import DriveTokenProvider
from clinical_delivery import selection as delivery_selection, state as delivery_state, handoff as delivery_handoff

BROWSER_SOURCES=('exalab','eloisa','rayen')
CREDENTIAL_SOURCES=('syslab','mmrad','his')
from clinical_recovery import expected_request, recover, reconcile_sources
from clinical_state import ACTIVE, transition


def now():return datetime.now(ZoneInfo('Pacific/Easter')).isoformat()

class PersistentLauncher:
    def __init__(self, output, python, keychain, downloader, labs, services, archive_root=DEFAULT_ROOT,
                 verifier=None, autostart=True, process_factory=subprocess.Popen):
        self.output=Path(output).resolve();self.output.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.python=python;self.keychain=keychain;self.downloader=Path(downloader);self.labs=labs;self.services=services
        self.archive_root=Path(archive_root);self.verifier=verifier or DriveVerifier(DriveTokenProvider(self.keychain))
        self.store=self.output/'.trabajos'/'cola.json';self.store.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.owner=open(self.store.with_suffix('.lock'),'a+b');os.chmod(self.store.with_suffix('.lock'),0o600)
        try:fcntl.flock(self.owner.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:self.owner.close();raise RuntimeError('Ya existe un lanzador para esta carpeta.')
        self.lock=threading.RLock();self.archive_lock=threading.Lock();self.payloads={};self.processes={};self.stop_event=threading.Event()
        self.wake=threading.Event();self.process_factory=process_factory;self.thread=None
        self.library_nonce=secrets.token_urlsafe(32)
        self.repository = QueueStore(self.store, self.output)
        try:
            snapshot = self.repository.load()
            self.jobs = snapshot.jobs
            self.quarantined = snapshot.quarantined
        except Exception:
            self.owner.close()
            raise
        for job in self.jobs.values():
            job['nonce']=secrets.token_urlsafe(24)
            if job['status'] in ('running','queued','interrupted','cancelling'):
                job['status'] = transition(job['status'], 'restart', cancelled=job['cancel_requested'])
                job['attempted']=True
                self._refresh(job)
                job['archive_dirty']=True
                if not job.get('cancel_requested'):
                    self._reconcile(job)
                    job['status'] = transition(job['status'], 'recovered', pending=bool(job['pending_sources']))
            self.payloads[job['id']]={}
            if job.get('attempted') and job['status'] not in ACTIVE:
                self._refresh(job);self._reconcile(job)
                job['status'] = transition(job['status'], 'review', pending=bool(job['pending_sources']))
                self._receipt(job);job['archive_dirty']=True
            if job.get('_recovery_error'):
                job['status'] = transition(job['status'], 'failed', cancelled=job['cancel_requested'])
        self._persist()
        if autostart:
            self.thread=threading.Thread(target=self._loop,daemon=True);self.thread.start()

    def _persist(self):
        self.repository.save(self.jobs)

    def credentials(self,source,submitted,remember):
        pair=submitted.get(source) or {}
        if not isinstance(pair,dict):raise ValueError('Credenciales inválidas.')
        values=[str(pair.get('username') or '').strip(),str(pair.get('password') or '')]
        if any(values) and not all(values):raise ValueError('Completa las credenciales de '+source+'.')
        if not any(values):values=[self.keychain.get(k) for k in self.services[source]]
        if not all(values):return None
        if remember and pair.get('password'):
            for key,value in zip(self.services[source],values):self.keychain.put(key,value)
        return dict(zip(('username','password'),values))

    def credential_status(self):
        out={}
        for source in CREDENTIAL_SOURCES:
            try:out[source]=bool(self.credentials(source,{},False))
            except Exception:out[source]=None
        return out

    def store_credentials(self,submitted):
        if not isinstance(submitted,dict) or not submitted or any(k not in self.services for k in submitted):raise ValueError('Fuentes inválidas.')
        for source,pair in submitted.items():
            if not isinstance(pair,dict) or not isinstance(pair.get('username'),str) or not isinstance(pair.get('password'),str) or not pair['username'].strip() or not pair['password'] or len(pair['password'])>1024:raise ValueError('Completa usuario y clave.')
        for source in submitted:self.credentials(source,submitted,True)
        with self.lock:
            for job in self.jobs.values():
                job['status'] = transition(job['status'], 'credentials', cancelled=job['cancel_requested'])
            self._persist()
        self.wake.set();return {'saved':list(submitted)}

    def new_job(self,request):
        from clinical_request import validate_request
        request = validate_request(request, local=True)
        from clinical_request import request_fingerprint
        with self.lock:
            request_id = request.get('requestId')
            fingerprint = request_fingerprint(request) if request_id else None
            if request_id:
                if any(item.get('request_id') == request_id for item in self.quarantined):
                    raise ValueError('Esta solicitud tiene un trabajo apartado; revisa su respaldo antes de reenviarla.')
                previous = next((job for job in self.jobs.values() if job.get('request_id') == request_id), None)
                if previous:
                    if previous['request_fingerprint'] != fingerprint:
                        raise ValueError('El identificador ya existe con otro contenido. Crea una solicitud nueva.')
                    return dict(self._bridge_request(previous), reused=True)
            if len(self.jobs) >= 1000:
                raise ValueError('La cola alcanzó 1000 trabajos; archiva su historial antes de continuar.')
            return self._create_job(request, request_id, fingerprint)

    def _create_job(self, request, request_id, fingerprint):
        ruts=request['ruts'];source=request['source'];selected=self.labs.selected_sources(source)
        period=request['period'];scope=request['eloisaScope'];mode=request['mmradMode']
        image_types=request['mmradImageTypes'];source_periods=request['sourcePeriods'];source_content=request['sourceContent']
        email_account=request['emailAccount'];delivery=delivery_selection(request['deliveryModel'],request['deliveryInstructions'])
        submitted=request.get('credentials',{})
        payload={};states={}
        for name in selected:
            if name in CREDENTIAL_SOURCES:
                try:pair=self.credentials(name,submitted,request.get('remember') is True)
                except Exception:pair=None
                if pair:payload[name]=pair
                states[name]='queued' if pair else 'needs_credentials'
            else:states[name]='needs_codex' if name=='email' else 'needs_session'
        ident=secrets.token_urlsafe(16)
        job={'id':ident,'nonce':secrets.token_urlsafe(24),'status':'queued','selected':selected,'source':source,'ruts':ruts,'period':period,
             'email_account':email_account,'delivery':delivery,'source_periods':source_periods,'source_content':source_content,'eloisa_scope':scope,'mmrad_mode':mode,'mmrad_image_types':list(image_types),'merge':request.get('merge') is True,'patient_merge':request.get('patientMerge') is True,
             'lines':[],'files':[],'summary':[],'code':None,'started_at':now(),'updated_at':now(),'checkpoint':None,
             'work_output':str(self.output/'.trabajos'/ident/'datos'),'pending_sources':selected.copy(),'source_states':states,
             'attempted':False,'cancel_requested':False,'archive':{'status':'pending','sync':'pending','files':[]},'as_of':request.get('asOf',datetime.now(ZoneInfo('Pacific/Easter')).date().isoformat())}
        with self.lock:
            if len(self.jobs)>=1000:raise ValueError('La cola alcanzó 1000 trabajos; archiva su historial antes de continuar.')
            if request_id:
                job.update(request_id=request_id, request_fingerprint=fingerprint)
            self.jobs[ident] = job
            self.payloads[ident] = payload
            try:
                self._receipt(job)
                job['archive_dirty'] = True
                self._persist()
            except Exception:
                self.jobs.pop(ident, None)
                self.payloads.pop(ident, None)
                payload.clear()
                raise
        self.wake.set();return dict(self._bridge_request(job), reused=False)

    def _bridge_request(self,job):
        return {'id':job['id'],'nonce':job['nonce'],'need':[] if job.get('cancel_requested') else [s for s in job['pending_sources'] if s in BROWSER_SOURCES and s not in self.payloads.get(job['id'],{}) and s not in job.get('_running_sources',[])]}

    def provide_sessions(self,submitted):
        if not isinstance(submitted,dict):raise ValueError('Sesión inválida.')
        with self.lock:
            job=self.jobs.get(submitted.get('id'))
            if not job or job.get('cancel_requested') or not secrets.compare_digest(str(submitted.get('nonce','')),job['nonce']):raise ValueError('Solicitud de sesiones vencida.')
            accepted=[]
            for source in BROWSER_SOURCES:
                if source not in job['pending_sources'] or source not in submitted:continue
                value=submitted[source]
                valid=isinstance(value,dict)
                if source=='eloisa':valid=valid and isinstance(value.get('access_token'),str) and bool(value['access_token'])
                if source=='exalab':valid=valid and isinstance(value.get('cookies'),list) and bool(value['cookies'])
                if source=='rayen':valid=valid and isinstance(value.get('token'),str) and bool(value['token']) and type(value.get('facilityId')) is int and value['facilityId']>0
                if valid:
                    self.payloads[job['id']][source]=value;job['source_states'][source]='queued';accepted.append(source)
            if accepted:
                job['status'] = transition(job['status'], 'sessions', cancelled=job['cancel_requested'])
            self._persist()
        self.wake.set();return {'accepted':accepted,'pending':[s for s in self._bridge_request(job)['need'] if s not in accepted]}

    def retry(self,ident):
        with self.lock:
            job=self.jobs.get(ident)
            if not job:raise ValueError('Trabajo no encontrado.')
            if job['status'] in ('running', 'cancelling'):
                raise ValueError('Espera a que termine la ejecución o cancelación.')
            self._refresh(job)
            if job.get('_recovery_error'):raise ValueError('Avance incompatible o ilegible. Los documentos se conservan; crea otra solicitud.')
            if job['summary']:self._reconcile(job)
            job['cancel_requested']=False
            job['pending_sources']=[s for s in job['selected'] if job['source_states'].get(s)!='complete']
            job['status'] = transition(job['status'], 'retry', pending=bool(job['pending_sources']))
            job['archive_dirty'] = True
            self._persist()
        if not job['pending_sources']:self._archive(job)
        self.wake.set();return self._bridge_request(job)

    def cancel_waiting(self,ident):return self.cancel(ident)

    def cancel(self,ident):
        with self.lock:
            job=self.jobs.get(ident)
            if not job:raise ValueError('Trabajo no encontrado.')
            job['cancel_requested']=True;self.payloads[ident]={}
            proc = self.processes.get(ident)
            job['status'] = transition(job['status'], 'cancel', has_process=proc is not None or job['status'] == 'running')
            self._persist()
        if not proc:self._archive(job)
        if proc:threading.Thread(target=self._stop_process,args=(proc,),daemon=True).start()
        return {'ok':True}

    def _stop_process(self,proc):
        try:
            if proc.poll() is not None:return
            proc.send_signal(signal.SIGINT)
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:proc.wait(timeout=3)
                except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=3)
        except (ProcessLookupError,OSError):pass

    def _ready(self,job):
        ready=[];payload=self.payloads[job['id']]
        for source in job['pending_sources']:
            if source in CREDENTIAL_SOURCES and source not in payload:
                try:pair=self.credentials(source,{},False)
                except Exception:pair=None
                if pair:payload[source]=pair
                else:job['source_states'][source]='needs_credentials'
            if source in payload or source=='email':ready.append(source)
        return ready

    def _loop(self):
        while not self.stop_event.is_set():
            chosen=None
            archive_job=None
            with self.lock:
                for job in self.jobs.values():
                    if job.get('archive_dirty') and job['status'] in ('complete','attention','cancelled','waiting'):
                        archive_job=job
                    if job['status'] not in ('queued','interrupted'):continue
                    try:
                        ready = self._ready(job)
                        if ready:
                            job['status'] = transition(job['status'], 'dispatch', cancelled=job['cancel_requested'])
                            chosen = (job, ready)
                            self._persist()
                            break
                        job['status'] = transition(job['status'], 'wait', cancelled=job['cancel_requested'])
                        self._receipt(job)
                        job['archive_dirty'] = True
                        self._persist()
                    except (ValueError, KeyError, TypeError, RuntimeError):
                        job['status'] = transition(job['status'], 'failed', cancelled=job['cancel_requested'])
                        job['lines'] = (job['lines'] + ['Preparación interrumpida; revisión pendiente. Los demás trabajos continúan.'])[-60:]
                        self._persist()
            if chosen:self._run(*chosen)
            elif archive_job:self._archive(archive_job)
            else:
                self.wake.wait(1);self.wake.clear()

    def _run(self,job,ready):
        with self.lock:
            job['_running_sources']=list(ready)
            for source in ready:job['source_states'][source]='running'
            payload={s:self.payloads[job['id']].pop(s) for s in ready if s in self.payloads[job['id']]}
            args=[self.python,str(Path(__file__).with_name('clinical_worker.py')),str(os.getpid()),str(self.downloader),'--session-stdin','--source',job['source'],'--period',job['period'],
                  '--output',job['work_output'],'--ruts',*job['ruts'],'--eloisa-scope',job['eloisa_scope'],'--mmrad-mode',job['mmrad_mode'],
                  '--ready-sources',','.join(ready),'--cache-dir',str(self.output/'.cache-documentos')]
            if 'email' in job['selected']:args+=['--email-account',job['email_account']]
            if job.get('source_content'):
                args+=['--source-content',json.dumps(job['source_content'],sort_keys=True)]
            if job.get('source_periods'):
                args+=['--source-periods',json.dumps(job['source_periods'],sort_keys=True)]
            if 'mmrad' in job['selected']:
                args+=['--mmrad-image-types',','.join(job.get('mmrad_image_types',('radiographs','ultrasounds')))]
            if job['checkpoint']:args+=['--resume',job['checkpoint'],'--retry-sources',','.join(ready)]
            else:args+=['--as-of',job['as_of']]
            if job['merge']:args.append('--merge')
            if job['patient_merge']:args.append('--patient-merge')
            job['attempted']=True
        try:
            proc=self.process_factory(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1,start_new_session=True)
            with self.lock:self.processes[job['id']]=proc
            if job.get('cancel_requested') or self.stop_event.is_set():self._stop_process(proc)
            else:
                proc.stdin.write(json.dumps(payload));proc.stdin.close()
            payload.clear()
            def consume(stream):
                for line in stream:
                    line=line.strip()
                    if not line:continue
                    with self.lock:
                        job['lines']=(job['lines']+[line])[-60:]
                        if line.startswith('Avance: '):job['checkpoint']=line[8:]
                        if line.startswith('Resumen: '):job['result_path']=line[9:]
                        job['updated_at']=now();self._persist()
                stream.close()
            threads=[threading.Thread(target=consume,args=(stream,),daemon=True) for stream in (proc.stdout,proc.stderr)]
            for thread in threads:thread.start()
            code=proc.wait()
            for thread in threads:thread.join()
            with self.lock:
                self.processes.pop(job['id'],None);job['code']=code;self._refresh(job)
                self._reconcile(job);pending=job['pending_sources']
                # Sesiones entregadas mientras corría otra fuente quedan listas para su turno.
                job['status'] = transition(job['status'], 'finish', pending=bool(pending),
                    cancelled=job['cancel_requested'], stopping=self.stop_event.is_set(),
                    ready=any(source in self.payloads[job['id']] for source in pending))
                job['archive_dirty']=True;self._persist()
            self._archive(job)
        except Exception as error:
            with self.lock:
                job['lines'].append('Ejecución interrumpida: '+type(error).__name__+'. Los archivos previos se conservan.')
                job['status'] = transition(job['status'], 'failed', cancelled=job['cancel_requested'])
                self._refresh(job)
                self._reconcile(job)
                self._persist()
            self._archive(job)
        finally:
            payload.clear()
            with self.lock:
                job.pop('_running_sources',None)
                proc=self.processes.pop(job['id'],None)
            if proc and proc.poll() is None:self._stop_process(proc)
            self.wake.set()

    def _reconcile(self, job):
        progress = reconcile_sources(job)
        job['source_states'] = progress.states
        job['pending_sources'] = progress.pending

    def _expected_request(self, job):
        return expected_request(job)

    def _refresh(self, job):
        recovered = recover(job, self.labs)
        job.update(checkpoint=recovered.checkpoint, files=recovered.files,
                   summary=recovered.summary['results'], _summary=recovered.summary,
                   _recovery_error=recovered.failed, _integrity_cache=recovered.cache)
        for message in recovered.messages:
            if message not in job['lines']:
                job['lines'] = (job['lines'] + [message])[-60:]

    def _receipt(self,job):
        from clinical_receipt import write
        summary=dict(job.get('_summary') or {})
        summary.update(source=job['source'],ruts=job['ruts'],period=job['period'],source_periods=job.get('source_periods',{}),source_content=job.get('source_content',{}),
                       as_of=job['as_of'],mmrad_mode=job['mmrad_mode'],email_account=job.get('email_account'),
                       order_status=job['status'],results=job['summary'])
        job['receipts']=write(summary,job['work_output']);job['_summary']=summary

    def mail_request(self,ident):
        from clinical_email import handoff
        with self.lock:
            job=self.jobs.get(ident)
            if not job or 'email' not in job['selected']:raise ValueError('Correo no solicitado.')
            return handoff(job)

    def _archive(self,job):
        with self.archive_lock:self._archive_once(job)

    def _archive_once(self,job):
        try:
            from clinical_artifacts import states
            with self.lock:
                self._review_status(job);self._receipt(job);summary=copy.deepcopy(job['_summary'])
                summary['publication_job']={k:job[k] for k in ('id','as_of','started_at')}
                summary['artifact_states']=states(job)
                summary['artifacts']=[r['artifact'] for r in summary['artifact_states'] if r['status'] in ('verified','archived')]
            result=PatientArchive(job['work_output'],self.archive_root,self.verifier).archive(summary) if summary else {'status':'pending','sync':'pending','files':[]}
        except Exception:result={'status':'pending','sync':'pending','files':[],'pending':['Archivo en Drive pendiente; documentos locales conservados.']}
        with self.lock:job['archive']=result;job['archive_dirty']=False;self._persist()

    def verify_archive(self,ident):
        with self.lock:
            job=self.jobs.get(ident)
            if not job:raise ValueError('Trabajo no encontrado.')
            if job['status']=='running':raise ValueError('Espera a que termine el trabajo.')
        self._archive(job);return job['archive']

    def _review_status(self,job):
        before=(copy.deepcopy(job['summary']),copy.deepcopy(job['files']),job['status'])
        self._refresh(job)
        if job['summary'] and job['status'] not in ('running','cancelling','queued'):
            self._reconcile(job)
            job['status'] = transition(job['status'], 'review', pending=bool(job['pending_sources']))
        if before!=(job['summary'],job['files'],job['status']):
            self._receipt(job);job['archive_dirty']=True;self._persist();self.wake.set()

    def status(self,ident):
        from clinical_artifacts import states
        with self.lock:
            job=self.jobs.get(ident)
            if not job:raise ValueError('Solicitud no encontrada.')
            self._review_status(job)
            products=states(job)
            fulfillment='complete' if job['status']=='complete' and job['archive'].get('status')=='complete' and all(p['status']=='archived' for p in products) else 'pending'
            return {'id':ident,'status':job['status'],**self._bridge_request(job),'lines':list(job['lines']),
                    'receipts':[dict(r,index=i) for i,r in enumerate(job.get('receipts',[]))],
                    'email_account':job.get('email_account'),'summary':copy.deepcopy(job['summary']),'source_states':dict(job['source_states']),'code':job['code'],
                    'archive':copy.deepcopy(job['archive']),'started_at':job['started_at'],'delivery':delivery_state(job),'artifacts':products,'fulfillment':fulfillment,'period':job['period'],'source_periods':dict(job.get('source_periods',{})),'source_content':copy.deepcopy(job.get('source_content',{})),
                    'files':[{'name':f['name'],'source':f['source'],'rut':f['rut'],'index':i,'sha256':f['sha256']} for i,f in enumerate(job['files'])]}

    def delivery_request(self,ident):
        with self.lock:
            job=self.jobs.get(ident)
            if not job:raise ValueError('Solicitud no encontrada.')
            self._review_status(job)
            self._receipt(job);self._persist()
            return delivery_handoff(job,self.output)

    def register_delivery(self,submission):
        from clinical_artifacts import register, states
        with self.archive_lock:
            with self.lock:
                job=self.jobs.get(submission.get('jobId'))
                if not job:raise ValueError('Solicitud no encontrada.')
                self._review_status(job)
                result=register(job,submission)
                job['archive_dirty']=True;self._persist()
            self._archive_once(job)
            with self.lock:return {'key':result['key'],'reused':result['reused'],'artifacts':states(job)}

    def history(self):
        with self.lock:return [{'id':j['id'],'status':j['status'],'started_at':j['started_at'],'sources':j['selected'],'patients':len(j['ruts']),'delivery':delivery_state(j)} for j in reversed(list(self.jobs.values()))]

    def library(self):
        from clinical_library import ClinicalLibrary
        return ClinicalLibrary(self.archive_root)

    def transport_status(self,ident):
        from clinical_artifacts import states
        from clinical_presence import project
        with self.lock:
            job=self.jobs.get(ident)
            if not job:raise ValueError('Solicitud no encontrada.')
            return project(job,states(job))

    def close(self):
        self.stop_event.set();self.wake.set()
        with self.lock:processes=list(self.processes.values())
        for proc in processes:self._stop_process(proc)
        if self.thread:self.thread.join(timeout=12)
        self._persist();fcntl.flock(self.owner.fileno(),fcntl.LOCK_UN);self.owner.close()
