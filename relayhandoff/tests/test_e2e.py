import base64, concurrent.futures, hashlib, json, os, subprocess, sys, tempfile, threading, time, unittest, urllib.request, urllib.error, uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'sdk')]
from server import serve
from python_client import Client

class E2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.db=str(Path(cls.temp.name)/'state.db')
        cls.keys={'source-'+'s'*40:{'tenant':'a','actor':'python','role':'worker'},'target-'+'t'*40:{'tenant':'a','actor':'node','role':'worker'},'other-'+'o'*40:{'tenant':'b','actor':'other','role':'worker'},'reader-'+'r'*40:{'tenant':'a','actor':'audit','role':'reader'}}
        cls.start()
    @classmethod
    def start(cls):
        cls.server=serve('127.0.0.1',0,cls.db,cls.keys);cls.url='http://127.0.0.1:'+str(cls.server.server_port)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.source=Client(cls.url,'source-'+'s'*40);cls.target=Client(cls.url,'target-'+'t'*40)
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.temp.cleanup()
    def new(self,ttl=60):
        t=self.source.call('',{'state':{'steps':['python-checkpoint'],'unicode':'繁體中文','number':1.0}})
        return t['id'],self.source.call('/'+t['id']+'/acquire',{'ttl':ttl})
    def fault(self,code,fn):
        with self.assertRaises(urllib.error.HTTPError) as e:fn()
        self.assertEqual(e.exception.code,code)
        return json.load(e.exception)['error']
    def prepare(self,tid,lease,**kw):return self.source.call('/'+tid+'/prepare',{**lease,'revision':0,'summary':'Continue from verified checkpoint',**kw})
    def test_01_python_to_node_actual_process(self):
        tid,lease=self.new();raw='Python checkpoint — 繁體中文'.encode()
        state=self.source.call('/'+tid+'/write',{**lease,'revision':0,'state':{'steps':['python-checkpoint'],'unicode':'繁體中文','number':1.0},'artifacts':[{'name':'checkpoint.txt','base64':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest()}]})
        h=self.source.call('/'+tid+'/prepare',{**lease,'revision':state['revision'],'summary':'Continue in Node; validate attachment first.'})
        run=subprocess.run(['node',str(ROOT/'examples/node_target.mjs'),self.url,tid,h['handoff_id'],h['sha256']],env={**os.environ,'RH_TARGET_KEY':'target-'+'t'*40},capture_output=True,text=True,timeout=20)
        self.assertEqual(run.returncode,0,run.stderr);proof=json.loads(run.stdout)
        self.assertTrue(proof['verified_attachment']);self.assertEqual(proof['state']['steps'],['python-checkpoint','node-resumed'])
        self.assertEqual(proof['epoch'],lease['epoch']+1)
        self.fault(409,lambda:self.source.call('/'+tid+'/write',{**lease,'revision':2,'state':{'overwrite':True}}))
        Path(os.environ.get('RH_PROOF','/tmp/relayhandoff-proof.json')).write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    def test_02_restart_preserves_handoff_and_idempotency(self):
        tid,lease=self.new();h=self.prepare(tid,lease);key=str(uuid.uuid4());body={'handoff_id':h['handoff_id']}
        claim=self.target.call('/'+tid+'/claim',body,key)
        self.server.shutdown();self.server.server_close();self.thread.join();type(self).start()
        self.assertEqual(self.source.call('/'+tid)['phase'],'CLAIMED')
        self.assertEqual(self.target.call('/'+tid+'/claim',body,key),claim)
        envelope,b=self.target.bundle(tid,h['sha256'])
        self.target.call('/'+tid+'/ack',{**claim,'sha256':envelope['sha256']})
        self.assertEqual(self.source.call('/'+tid)['owner'],'node')
    def test_03_writes_frozen_before_ack(self):
        tid,l=self.new();h=self.prepare(tid,l)
        self.fault(409,lambda:self.source.call('/'+tid+'/write',{**l,'revision':0,'state':{}}))
        claim=self.target.call('/'+tid+'/claim',{'handoff_id':h['handoff_id']})
        self.fault(409,lambda:self.target.call('/'+tid+'/write',{**claim,'revision':0,'state':{}}))
        self.fault(409,lambda:self.target.call('/'+tid+'/ack',{**claim,'sha256':'0'*64}))
        self.assertEqual(self.source.call('/'+tid)['phase'],'CLAIMED')
    def test_04_cancel_invalidates_claim_and_source_token(self):
        tid,l=self.new();h=self.prepare(tid,l);claim=self.target.call('/'+tid+'/claim',{'handoff_id':h['handoff_id']})
        resumed=self.source.call('/'+tid+'/cancel',{'handoff_id':h['handoff_id']})
        self.assertGreater(resumed['epoch'],claim['epoch'])
        self.fault(409,lambda:self.target.call('/'+tid+'/ack',{**claim,'sha256':h['sha256']}))
        self.fault(409,lambda:self.source.call('/'+tid+'/write',{**l,'revision':0,'state':{}}))
        self.source.call('/'+tid+'/write',{**resumed,'revision':0,'state':{'recovered':True}})
    def test_05_tenant_isolation_and_reader(self):
        tid,l=self.new();other=Client(self.url,'other-'+'o'*40);reader=Client(self.url,'reader-'+'r'*40)
        self.fault(404,lambda:other.call('/'+tid));self.fault(404,lambda:other.call('/'+tid+'/acquire',{}))
        self.assertEqual(reader.call('/'+tid)['id'],tid)
        self.fault(403,lambda:reader.call('/'+tid+'/acquire',{}))
        self.fault(401,lambda:Client(self.url,'invalid').call('/'+tid))
    def test_06_acquire_concurrency_single_owner(self):
        tid=self.source.call('',{'state':{}})['id']
        def run(client):
            try:return client.call('/'+tid+'/acquire',{})
            except urllib.error.HTTPError as e:return e.code
        with concurrent.futures.ThreadPoolExecutor(2) as pool:out=list(pool.map(run,[self.source,self.target]))
        self.assertEqual(sum(isinstance(x,dict) for x in out),1);self.assertIn(409,out)
    def test_07_idempotency_key_conflict(self):
        key=str(uuid.uuid4());a=self.source.call('',{'state':{}},key);b=self.source.call('',{'state':{}},key)
        self.assertEqual(a,b);self.fault(409,lambda:self.source.call('',{'state':{'changed':True}},key))
    def test_08_expired_lease_rejected(self):
        tid,l=self.new(ttl=2);time.sleep(2.1)
        self.fault(409,lambda:self.source.call('/'+tid+'/write',{**l,'revision':0,'state':{}}))
        new=self.target.call('/'+tid+'/acquire',{});self.assertGreater(new['epoch'],l['epoch'])
    def test_09_handoff_timeout_recovery(self):
        tid,l=self.new();h=self.prepare(tid,l,timeout=2)
        claim=self.target.call('/'+tid+'/claim',{'handoff_id':h['handoff_id']});time.sleep(2.1)
        self.fault(409,lambda:self.target.call('/'+tid+'/ack',{**claim,'sha256':h['sha256']}))
        new=self.source.call('/'+tid+'/acquire',{});self.assertGreater(new['epoch'],claim['epoch'])
        self.source.call('/'+tid+'/write',{**new,'revision':0,'state':{'recovered':True}})
    def test_10_artifact_corruption_and_revision(self):
        tid,l=self.new()
        self.fault(400,lambda:self.source.call('/'+tid+'/write',{**l,'revision':0,'state':{},'artifacts':[{'name':'a','base64':'YWJj','sha256':'0'*64}]}))
        self.fault(409,lambda:self.source.call('/'+tid+'/write',{**l,'revision':5,'state':{}}))
        self.assertEqual(self.source.call('/'+tid)['revision'],0)
    def test_11_audit_chain(self):
        tid,l=self.new();self.prepare(tid,l);events=self.source.call('/'+tid+'/events')['events']
        previous=None
        for e in events:
            p=json.loads(e['payload']);raw=json.dumps(p,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),e['hash'])
            if previous is not None:self.assertEqual(p['previous'],previous)
            previous=e['hash']
        self.assertEqual([json.loads(x['payload'])['kind'] for x in events],['created','acquire','prepare'])
    def test_12_dashboard_and_health(self):
        with urllib.request.urlopen(self.url+'/') as r:self.assertIn(b'RelayHandoff',r.read())
        with urllib.request.urlopen(self.url+'/health') as r:self.assertTrue(json.load(r)['ok'])
    def test_13_wrong_owner_and_duplicate_claim(self):
        tid,l=self.new()
        self.fault(409,lambda:self.target.call('/'+tid+'/renew',l))
        h=self.prepare(tid,l);self.target.call('/'+tid+'/claim',{'handoff_id':h['handoff_id']})
        self.fault(409,lambda:self.source.call('/'+tid+'/claim',{'handoff_id':h['handoff_id']}))
        self.fault(409,lambda:self.target.call('/'+tid+'/cancel',{'handoff_id':h['handoff_id']}))
    def test_14_binary_preservation_and_sdk_hash_rejection(self):
        tid,l=self.new();raw=bytes(range(256))
        self.source.call('/'+tid+'/write',{**l,'revision':0,'state':{},'artifacts':[{'name':'binary.bin','base64':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest()}]})
        h=self.source.call('/'+tid+'/prepare',{**l,'revision':1,'summary':'binary'})
        e,b=self.target.bundle(tid,h['sha256']);self.assertEqual(base64.b64decode(b['artifacts']['binary.bin']['base64']),raw)
        with self.assertRaises(ValueError):self.target.bundle(tid,'0'*64)
    def test_15_two_checkpoints_cas_race(self):
        tid,l=self.new()
        def write(n):
            try:return self.source.call('/'+tid+'/write',{**l,'revision':0,'state':{'n':n}})
            except urllib.error.HTTPError as e:return e.code
        with concurrent.futures.ThreadPoolExecutor(2) as pool:out=list(pool.map(write,[1,2]))
        self.assertEqual(sum(isinstance(x,dict) for x in out),1);self.assertIn(409,out)

    def test_16_task_listing_is_scoped(self):
        tid,l=self.new()
        self.assertIn(tid,[x['id'] for x in self.source.call('')['tasks']])
        self.assertNotIn(tid,[x['id'] for x in Client(self.url,'other-'+'o'*40).call('')['tasks']])
    def test_17_ack_and_cancel_race_one_winner(self):
        tid,l=self.new();h=self.prepare(tid,l);claim=self.target.call('/'+tid+'/claim',{'handoff_id':h['handoff_id']})
        def run(n):
            try:
                if n==0:return self.target.call('/'+tid+'/ack',{**claim,'sha256':h['sha256']})
                return self.source.call('/'+tid+'/cancel',{'handoff_id':h['handoff_id']})
            except urllib.error.HTTPError as e:return e.code
        with concurrent.futures.ThreadPoolExecutor(2) as pool:out=list(pool.map(run,[0,1]))
        self.assertEqual(sum(isinstance(x,dict) for x in out),1);self.assertIn(409,out)
    def test_18_request_validation(self):
        tid,l=self.new()
        self.fault(400,lambda:self.source.call('/'+tid+'/renew',{**l,'ttl':True}))
        self.fault(400,lambda:self.source.call('/'+tid+'/prepare',{**l,'revision':0,'summary':''}))
        req=urllib.request.Request(self.url+'/v1/tasks',data=b'{bad json',headers={'Authorization':'Bearer '+'source-'+'s'*40,'Content-Type':'application/json','Idempotency-Key':str(uuid.uuid4())})
        self.fault(400,lambda:urllib.request.urlopen(req))
        req=urllib.request.Request(self.url+'/v1/tasks',data=b'{}',headers={'Authorization':'Bearer '+'source-'+'s'*40,'Content-Type':'text/plain'})
        self.fault(415,lambda:urllib.request.urlopen(req))

if __name__=='__main__': unittest.main(verbosity=2)
