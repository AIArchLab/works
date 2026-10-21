import hashlib,json,os,pathlib,sqlite3,subprocess,sys,tempfile,threading,time,unittest
from unittest import mock
from taskloop.core import Store,Engine,Network,PolicyError,canonical,sign
from taskloop.receiver import server

SECRET='test-only-secret-not-for-deployment'

class TestAgent:
    def __init__(self): self.calls=[]
    def decide(self,spec,observation):
        self.calls.append('report' if observation is not None else 'inspect')
        return {'action':'inspect'} if observation is None else {'action':'report','summary':'Observed HTTP status: '+str(observation['status'])}

class FakeNetwork:
    def __init__(self,fail=0,bad_receipt=False):self.gets=0;self.posts=0;self.fail=fail;self.bad=bad_receipt
    def request(self,method,url,data=None,headers=None,limit=65536):
        if method=='GET':self.gets+=1;return 200,{},b'example'
        self.posts+=1
        if self.fail>0:self.fail-=1;return 503,{},b'unavailable'
        p=json.loads(data);r={'accepted':True,'event_id':p['event_id'],'payload_sha256':hashlib.sha256(data).hexdigest(),'receipt_id':'test-receipt'}
        if self.bad:r['event_id']='wrong-event'
        body=canonical(r);return 200,{'x-taskloop-signature':sign(SECRET,body)},body

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=pathlib.Path(self.tmp.name)/'tasks.sqlite3';self.s=Store(self.path);self.agent=TestAgent();self.net=FakeNetwork();self.e=Engine(self.s,self.agent,self.net,SECRET,retry_base=1);self.now=time.time()
    def tearDown(self):self.s.db.close();self.tmp.cleanup()
    def submit(self,id='sample',due=None):return self.s.submit(id,'https://check.example/health','https://notify.example/inbox',self.now if due is None else due)
    def test_owner_survives_reopen(self):
        self.s.submit('sample','https://check.example','https://notify.example',self.now,owner='sample-agent');other=Store(self.path)
        try:self.assertEqual(other.status('sample')['owner'],'sample-agent')
        finally:other.db.close()
    def test_non_finite_due_rejected(self):self.assertRaises(ValueError,self.s.submit,'bad','https://check.example','https://notify.example',float('nan'))
    def test_secret_bearing_query_rejected_before_store(self):self.assertRaises(ValueError,self.s.submit,'bad','https://check.example/?token=secret','https://notify.example',self.now)
    def test_submit_is_idempotent(self):self.assertTrue(self.submit());self.assertFalse(self.submit())
    def test_duplicate_id_different_spec_rejected(self):self.submit();self.assertRaises(ValueError,self.s.submit,'sample','https://other.example','https://notify.example/inbox',self.now)
    def test_future_task_not_executed(self):self.submit(due=self.now+100);self.assertFalse(self.e.execute_one(self.now));self.assertEqual(self.net.gets,0)
    def test_model_tool_model_flow(self):self.submit();self.e.execute_one(self.now);self.assertEqual(self.agent.calls,['inspect','report']);self.assertEqual(self.net.gets,1)
    def test_execution_is_not_completion(self):self.submit();self.e.execute_one(self.now);self.assertEqual(self.s.status('sample')['state'],'AWAITING_DELIVERY')
    def test_signed_bound_receipt_completes(self):self.submit();self.e.execute_one(self.now);self.e.deliver_one(self.now);self.assertEqual(self.s.status('sample')['state'],'COMPLETED')
    def test_retry_does_not_rerun_check(self):
        self.net.fail=1;self.submit();self.e.execute_one(self.now);self.e.deliver_one(self.now);self.assertEqual(self.s.status('sample')['state'],'AWAITING_DELIVERY');self.e.deliver_one(self.now+2);self.assertEqual(self.s.status('sample')['state'],'COMPLETED');self.assertEqual(self.net.gets,1);self.assertEqual(self.net.posts,2)
    def test_wrong_event_receipt_not_completion(self):self.net.bad=True;self.submit();self.e.execute_one(self.now);self.e.deliver_one(self.now);self.assertEqual(self.s.status('sample')['state'],'AWAITING_DELIVERY')
    def test_unsigned_200_not_completion(self):
        self.submit();self.e.execute_one(self.now)
        with mock.patch.object(self.net,'request',return_value=(200,{},b'OK')):self.e.deliver_one(self.now)
        self.assertEqual(self.s.status('sample')['state'],'AWAITING_DELIVERY')
    def test_notification_exhaustion_is_blocked(self):
        self.net.fail=99;self.e.max_attempts=2;self.submit();self.e.execute_one(self.now);self.e.deliver_one(self.now);self.e.deliver_one(self.now+2);self.assertEqual(self.s.status('sample')['state'],'DELIVERY_BLOCKED')
    def test_no_second_delivery_after_ack(self):self.submit();self.e.execute_one(self.now);self.e.deliver_one(self.now);self.assertFalse(self.e.deliver_one(self.now+10));self.assertEqual(self.net.posts,1)
    def test_restart_resumes_delivery_only(self):
        self.submit();self.e.execute_one(self.now);self.s.db.close();self.s=Store(self.path);new_agent=TestAgent();e=Engine(self.s,new_agent,self.net,SECRET);self.assertFalse(e.execute_one(self.now+10));e.deliver_one(self.now+10);self.assertEqual(new_agent.calls,[]);self.assertEqual(self.s.status('sample')['state'],'COMPLETED')
    def test_checkpoint_recovers_after_lease_expires(self):
        self.submit();row=self.s.claim('tasks',self.now,lease=1);self.s.checkpoint(row,{'status':200,'observed_at':'test','bytes':2});self.assertFalse(self.e.execute_one(self.now));self.e.execute_one(self.now+2);self.assertEqual(self.net.gets,0);self.assertEqual(self.agent.calls,['report'])
    def test_stale_owner_cannot_checkpoint(self):
        self.submit();old=self.s.claim('tasks',self.now,lease=1);self.s.claim('tasks',self.now+2);self.assertRaises(RuntimeError,self.s.checkpoint,old,{'status':200})
    def test_two_connections_cannot_claim_same_task(self):
        self.submit();other=Store(self.path)
        try:self.assertIsNotNone(self.s.claim('tasks',self.now));self.assertIsNone(other.claim('tasks',self.now))
        finally:other.db.close()
    def test_result_and_outbox_are_atomic(self):
        self.submit();row=self.s.claim('tasks',self.now)
        self.s.db.execute("CREATE TRIGGER reject_outbox BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT,'fault'); END")
        self.assertRaises(sqlite3.IntegrityError,self.s.finish,row,{'verdict':'PASS'})
        self.assertEqual(self.s.db.execute('SELECT execution FROM tasks').fetchone()[0],'running');self.assertEqual(self.s.db.execute('SELECT count(*) FROM outbox').fetchone()[0],0)
    def test_invalid_agent_cannot_finish_without_tool(self):
        self.submit()
        with mock.patch.object(self.agent,'decide',return_value={'action':'report','summary':'invented'}):self.e.execute_one(self.now)
        self.assertEqual(self.net.gets,0);self.assertEqual(self.s.status('sample')['state'],'EXECUTION_PENDING')
    def test_model_url_override_is_ignored(self):
        self.submit();original=self.agent.decide
        def decide(spec,obs):
            d=original(spec,obs);d['url']='http://169.254.169.254/';return d
        with mock.patch.object(self.agent,'decide',side_effect=decide):self.e.execute_one(self.now)
        self.assertEqual(self.net.gets,1)
    def test_exhausted_agent_failure_is_reportable(self):
        self.submit();self.e.max_attempts=1
        with mock.patch.object(self.agent,'decide',side_effect=ValueError('failure')):self.e.execute_one(self.now)
        self.e.deliver_one(self.now);self.assertEqual(self.s.status('sample')['state'],'FAILED_REPORTED')
    def test_expected_status_is_independent_of_prose(self):
        self.s.submit('sample','https://check.example','https://notify.example',self.now,expected=204);self.e.execute_one(self.now);self.assertEqual(self.s.status('sample')['result']['verdict'],'FAIL')

class PolicyTests(unittest.TestCase):
    def test_http_is_denied_by_default(self):self.assertRaises(PolicyError,Network(['example.com']).request,'GET','http://example.com')
    def test_unknown_host_is_denied(self):self.assertRaises(PolicyError,Network(['example.com']).request,'GET','https://other.example')
    def test_embedded_credentials_denied(self):self.assertRaises(PolicyError,Network(['example.com']).request,'GET','https://user:pass@example.com')
    def test_private_address_denied(self):self.assertRaises(PolicyError,Network(['127.0.0.1']).request,'GET','https://127.0.0.1')
    def test_metadata_address_denied_even_demo(self):self.assertRaises(PolicyError,Network(['169.254.169.254'],True).request,'GET','http://169.254.169.254')
    def test_short_secret_denied(self):self.assertRaises(ValueError,Engine,None,None,None,'short')

class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=pathlib.Path(self.tmp.name)/'inbox.sqlite3';self.server=server('127.0.0.1',0,self.path,SECRET);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.url='http://127.0.0.1:'+str(self.server.server_address[1])+'/inbox';self.net=Network(['127.0.0.1'],True)
    def tearDown(self):self.server.shutdown();self.thread.join();self.server.server_close();self.tmp.cleanup()
    def send(self,payload,secret=SECRET,ts=None):
        data=canonical(payload);ts=str(int(time.time())) if ts is None else str(ts);return self.net.request('POST',self.url,data,{'Content-Type':'application/json','Idempotency-Key':payload['event_id'],'X-Taskloop-Time':ts,'X-Taskloop-Signature':sign(secret,ts.encode()+b'.'+data)})
    def test_receiver_persists_and_deduplicates(self):
        one=self.send({'event_id':'test','result':1});two=self.send({'event_id':'test','result':1});self.assertEqual(one[0],200);self.assertEqual(one[2],two[2])
        with sqlite3.connect(self.path) as db:self.assertEqual(db.execute('SELECT count(*) FROM inbox').fetchone()[0],1)
    def test_same_id_different_payload_rejected(self):self.send({'event_id':'test','result':1});self.assertEqual(self.send({'event_id':'test','result':2})[0],409)
    def test_wrong_signature_rejected(self):self.assertEqual(self.send({'event_id':'test'},secret='wrong')[0],401)
    def test_expired_timestamp_rejected(self):self.assertEqual(self.send({'event_id':'test'},ts=1)[0],401)

class SubprocessRecoveryTests(unittest.TestCase):
    def test_process_death_after_checkpoint(self):
        with tempfile.TemporaryDirectory() as td:
            path=str(pathlib.Path(td)/'task.sqlite3');s=Store(path);s.submit('crash-test','https://check.example','https://notify.example',0);s.db.close()
            code="from taskloop.core import Store;import os;s=Store("+repr(path)+");r=s.claim('tasks',0,lease=1);s.checkpoint(r,{'status':200,'observed_at':'synthetic fixture'});os._exit(23)"
            result=subprocess.run([sys.executable,'-c',code],cwd=pathlib.Path(__file__).resolve().parents[1]);self.assertEqual(result.returncode,23)
            s=Store(path);agent=TestAgent();net=FakeNetwork();e=Engine(s,agent,net,SECRET);e.execute_one(2);e.deliver_one(2);self.assertEqual(agent.calls,['report']);self.assertEqual(net.gets,0);self.assertEqual(s.status('crash-test')['state'],'COMPLETED');s.db.close()

if __name__=='__main__':unittest.main(verbosity=2)
