"""Issue #2 acceptance gate: original 18 cases + RH-01..04 negative regressions."""
import base64,hashlib,json,os,subprocess,sys,unittest,uuid,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import test_e2e as original

class Issue2(original.E2E):
    def raw(self,path,body):
        data=json.dumps(body,ensure_ascii=False).encode()
        req=urllib.request.Request(self.url+'/v1/tasks'+path,data=data,headers={'Authorization':'Bearer '+'source-'+'s'*40,'Content-Type':'application/json','Idempotency-Key':str(uuid.uuid4())})
        with urllib.request.urlopen(req,timeout=15) as response:return json.load(response)
    def spawn_target(self,tid,h):
        return subprocess.run(['node',str(original.ROOT/'examples/node_target.mjs'),self.url,tid,h['handoff_id'],h['sha256']],env={**os.environ,'RH_TARGET_KEY':'target-'+'t'*40},capture_output=True,text=True,timeout=20)
    def negative_target(self,state,artifacts,error):
        tid,l=self.new()
        self.source.call('/'+tid+'/write',{**l,'revision':0,'state':state,'artifacts':artifacts})
        h=self.source.call('/'+tid+'/prepare',{**l,'revision':1,'summary':'Negative receiver semantics test'})
        p=self.spawn_target(tid,h);self.assertNotEqual(p.returncode,0);self.assertIn(error,p.stderr)
        current=self.source.call('/'+tid);self.assertEqual(current['phase'],'CLAIMED');self.assertEqual(current['expires'],0)
        kinds=[json.loads(e['payload'])['kind'] for e in self.source.call('/'+tid+'/events')['events']]
        self.assertNotIn('ack',kinds)
    def artifact(self,raw,name='checkpoint.txt'):
        return {'name':name,'base64':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest()}
    def test_19_nonportable_numbers_rejected_at_http_create_and_nested_write(self):
        tid,l=self.new()
        for value in [float('nan'),float('inf'),float('-inf'),9007199254740992,9007199254740993,-9007199254740992,-9007199254740993,1e30]:
            with self.subTest(value=repr(value)):
                expected='json_non_finite_number' if isinstance(value,float) and not __import__('math').isfinite(value) else 'json_number_out_of_range'
                state={'nested':[{'number':value}]}
                self.assertEqual(self.fault(400,lambda:self.raw('',{'state':state})),expected)
                self.assertEqual(self.fault(400,lambda:self.raw('/'+tid+'/write',{**l,'revision':0,'state':state})),expected)
        self.assertEqual(self.source.call('/'+tid)['revision'],0)
    def test_20_safe_number_boundaries_roundtrip_to_node(self):
        numbers=[9007199254740991,-9007199254740991,0,1.25,-0.5,1e-9]
        tid,l=self.new();self.source.call('/'+tid+'/write',{**l,'revision':0,'state':{'nested':[{'n':x} for x in numbers]}})
        h=self.source.call('/'+tid+'/prepare',{**l,'revision':1,'summary':'safe boundaries'})
        e,b=self.target.bundle(tid,h['sha256']);self.assertEqual([x['n'] for x in b['state']['nested']],numbers)
        script="import {Client} from './sdk/node_client.mjs';const c=new Client(process.env.URL,process.env.KEY);const {bundle}=await c.bundle(process.env.TASK,process.env.SHA);console.log(JSON.stringify(bundle.state.nested.map(x=>x.n)));"
        p=subprocess.run(['node','--input-type=module','-e',script],cwd=original.ROOT,env={**os.environ,'URL':self.url,'KEY':'target-'+'t'*40,'TASK':tid,'SHA':h['sha256']},capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(json.loads(p.stdout),numbers)
    def test_21_python_sdk_rejects_before_network_and_rejects_invalid_bundle(self):
        from python_client import Client
        for value in [float('nan'),float('inf'),float('-inf'),9007199254740992,-9007199254740992]:
            with self.assertRaises(ValueError):Client('http://127.0.0.1:1','test').call('',{'state':{'nested':[value]}})
        for value in [float('nan'),9007199254740993]:
            raw=json.dumps({'protocol':'relayhandoff/1','task_id':'test','state':{'n':value},'artifacts':{}}).encode()
            class Fake(Client):
                def call(self,*a,**kw):return {'bundle_base64':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest()}
            with self.assertRaises(ValueError):Fake('http://unused','test').bundle('test')
    def test_22_node_sdk_rejects_before_fetch_and_rejects_legacy_bundle(self):
        script=r"""import {Client} from './sdk/node_client.mjs';import {createHash} from 'node:crypto';
let calls=0;globalThis.fetch=async()=>{calls++;throw Error('unexpected_network')};
for(const n of [NaN,Infinity,-Infinity,9007199254740992,-9007199254740992]){
 try{await new Client('http://unused','key').call('',{state:{nested:[n]}});throw Error('accepted')}catch(e){if(!e.message.startsWith('json_'))throw e}
}
if(calls!==0)throw Error('sent_invalid_body');
for(const n of ['9007199254740993','NaN','1e400']){
 const raw=Buffer.from('{"protocol":"relayhandoff/1","task_id":"test","state":{"n":'+n+'},"artifacts":{}}');
 class Fake extends Client{async call(){return {bundle_base64:raw.toString('base64'),sha256:createHash('sha256').update(raw).digest('hex')}}}
 let rejected=false;try{await new Fake('http://unused','key').bundle('test')}catch(e){rejected=true}if(!rejected)throw Error('accepted_legacy_bundle');
}console.log('sdk guards passed');"""
        p=subprocess.run(['node','--input-type=module','-e',script],cwd=original.ROOT,capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr)
    def test_23_correct_hash_wrong_semantics_has_no_ack(self):
        self.negative_target({'steps':['ready']},[self.artifact(b'wrong but authentic')],'attachment_not_preserved')
    def test_24_missing_required_attachment_has_no_ack(self):
        self.negative_target({'steps':['ready']},[],'missing_required_attachment')
    def test_25_missing_required_state_has_no_ack(self):
        self.negative_target({},[self.artifact('Python checkpoint — 繁體中文'.encode())],'missing_required_state')
    def test_26_shared_snapshot_quota_ascii_and_multibyte(self):
        # Exact state+outputs canonical bytes, including wrapper overhead.
        from server import canonical,MAX_BODY
        tid,l=self.new();revision=0
        for unit in ['x','繁']:
            overhead=len(canonical({'state':{'x':''},'outputs':{}}));limit=MAX_BODY//2
            n=(limit-overhead)//len(unit.encode());state={'x':unit*n}
            self.assertLessEqual(len(canonical({'state':state,'outputs':{}})),limit)
            self.raw('',{'state':state})
            result=self.raw('/'+tid+'/write',{**l,'revision':revision,'state':state});revision=result['revision']
            oversized={'x':unit*(n+1)}
            self.assertGreater(len(canonical({'state':oversized,'outputs':{}})),limit)
            self.assertEqual(self.fault(413,lambda:self.raw('',{'state':oversized})),'task_snapshot_too_large')
            self.assertEqual(self.fault(413,lambda:self.raw('/'+tid+'/write',{**l,'revision':revision,'state':oversized})),'task_snapshot_too_large')
        self.assertEqual(self.source.call('/'+tid)['revision'],revision)
    def test_27_empty_artifact_full_bundle_ack_flow(self):
        tid,l=self.new();a=self.artifact(b'','empty.bin')
        self.source.call('/'+tid+'/write',{**l,'revision':0,'state':{'steps':[]},'artifacts':[a]})
        h=self.source.call('/'+tid+'/prepare',{**l,'revision':1,'summary':'empty binary is valid'})
        e,b=self.target.bundle(tid,h['sha256']);self.assertEqual(b['artifacts']['empty.bin']['base64'],'')
        script="import {Client} from './sdk/node_client.mjs';const c=new Client(process.env.URL,process.env.KEY);const e=await c.call('/'+process.env.TASK+'/claim',{handoff_id:process.env.HANDOFF});const {bundle,envelope}=await c.bundle(process.env.TASK,process.env.SHA);if(Buffer.from(bundle.artifacts['empty.bin'].base64,'base64').length!==0)throw Error('not_empty');await c.call('/'+process.env.TASK+'/ack',{...e,sha256:envelope.sha256});await c.call('/'+process.env.TASK+'/write',{...e,revision:bundle.revision,state:{verified_empty:true}});"
        p=subprocess.run(['node','--input-type=module','-e',script],cwd=original.ROOT,env={**os.environ,'URL':self.url,'KEY':'target-'+'t'*40,'TASK':tid,'SHA':h['sha256'],'HANDOFF':h['handoff_id']},capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr);self.assertTrue(self.source.call('/'+tid)['state']['verified_empty'])
    def test_28_release_receiver_missing_inputs_has_no_ack(self):
        for state,arts,error in [({},[],'missing_required_state'),({'product':'RelayHandoff','version':'0.1.0','stage':'built'},[],'missing_required_attachment'),({'product':'RelayHandoff','version':'0.1.0','stage':'built'},[self.artifact(b'{}','release-manifest.json')],'invalid_manifest')]:
            tid,l=self.new();self.source.call('/'+tid+'/write',{**l,'revision':0,'state':state,'artifacts':arts})
            h=self.source.call('/'+tid+'/prepare',{**l,'revision':1,'summary':'bad release input'})
            p=subprocess.run(['node',str(original.ROOT/'examples/release_target.mjs'),self.url,tid,h['handoff_id'],h['sha256'],str(original.ROOT)],env={**os.environ,'RH_TARGET_KEY':'target-'+'t'*40},capture_output=True,text=True,timeout=15)
            self.assertNotEqual(p.returncode,0);self.assertIn(error,p.stderr)
            self.assertEqual(self.source.call('/'+tid)['phase'],'CLAIMED')
            self.assertNotIn('ack',[json.loads(e['payload'])['kind'] for e in self.source.call('/'+tid+'/events')['events']])

if __name__=='__main__':unittest.main(verbosity=2)
