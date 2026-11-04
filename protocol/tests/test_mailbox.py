import contextlib,io,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mailbox as m

class MailboxTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def send(self,**kw):return m.send(self.root,'gpai','dsh-sd','test','synthetic task','key-1',**kw)
    def test_01_send_replay_and_changed_payload_conflict(self):
        a,paths=self.send();b,again=self.send();self.assertEqual(a,b);self.assertEqual(again,[])
        self.assertEqual(m.read_message(paths[0]),a)
        with self.assertRaisesRegex(ValueError,'idempotency'):m.send(self.root,'gpai','dsh-sd','changed','synthetic task','key-1')
    def test_02_receiver_restart_rescan_is_idempotent(self):
        a,_=self.send();report,paths=m.scan(self.root,'dsh-sd',True);self.assertEqual(len(paths),1)
        # Independent CLI process, no in-memory cursor survives.
        p=subprocess.run([sys.executable,str(Path(m.__file__)),'--repo',str(self.root),'--member','dsh-sd','scan','--receive'],capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(len(list((self.root/'inbox/_receipts').rglob('*.json'))),1)
        self.assertFalse(json.loads(p.stdout)['incoming'][0]['closed'])
    def test_03_delivery_acceptance_completion_verification_are_separate(self):
        a,_=self.send();mid=a['id']
        with self.assertRaisesRegex(ValueError,'acceptance'):m.record(self.root,'dsh-sd',mid,'completed','done',['commit:test'])
        m.scan(self.root,'dsh-sd',True);m.record(self.root,'dsh-sd',mid,'accepted','working')
        m.record(self.root,'dsh-sd',mid,'completed','done',['commit:test'])
        self.assertFalse(m.scan(self.root,'gpai')[0]['outgoing'][0]['closed'])
        m.record(self.root,'gpai',mid,'verified','checked',['commit:test'])
        self.assertTrue(m.scan(self.root,'gpai')[0]['outgoing'][0]['closed'])
    def test_04_cannot_ack_for_other_member(self):
        a,_=self.send()
        with self.assertRaisesRegex(ValueError,'owner'):m.record(self.root,'gpai',a['id'],'received')
        m.scan(self.root,'dsh-sd',True)
        with self.assertRaisesRegex(ValueError,'owner'):m.record(self.root,'dsh-sd',a['id'],'verified','fake',['commit:test'])
    def test_05_tampered_message_is_reported_without_hiding_valid_message(self):
        a,paths=self.send();bad=json.loads(paths[0].read_text());bad['body']='tampered';paths[0].write_text(json.dumps(bad))
        b,_=m.send(self.root,'gpai','dsh-sd','good','good','key-2')
        report,changed=m.scan(self.root,'dsh-sd',True)
        self.assertEqual(len(report['validation_errors']),1);self.assertEqual(report['incoming'][0]['id'],b['id'])
        self.assertEqual(len(changed),1)
    def test_06_reply_binds_original_route(self):
        a,_=self.send();b,_=m.send(self.root,'dsh-sd','gpai','reply','answer','reply-1',reply_to=a['id'])
        self.assertEqual(b['reply_to'],a['id'])
        with self.assertRaisesRegex(ValueError,'route'):m.send(self.root,'other','gpai','reply','answer','reply-2',reply_to=a['id'])
    def test_07_old_unreceived_message_never_disappears(self):
        a,paths=self.send();a.pop('sha256');a['created_at']='2020-01-01T00:00:00+00:00';a['sha256']=m.sha(a);paths[0].write_bytes(m.canonical(a))
        report,_=m.scan(self.root,'gpai');self.assertTrue(report['outgoing'][0]['delivery_overdue'])
        report,_=m.scan(self.root,'dsh-sd',True);self.assertIn('received',report['incoming'][0]['events'])
    def test_08_bad_paths_and_unbacked_completion_rejected(self):
        for member in ['../escape','../','_receipts']:
            with self.assertRaises(ValueError):m.send(self.root,'gpai',member,'s','b','k')
        a,_=self.send();m.scan(self.root,'dsh-sd',True);m.record(self.root,'dsh-sd',a['id'],'accepted')
        with self.assertRaisesRegex(ValueError,'evidence'):m.record(self.root,'dsh-sd',a['id'],'completed')
    def test_09_git_two_clones_offline_catchup_and_unpushed_receipt_retry(self):
        def run(*args):
            p=subprocess.run(['git',*map(str,args)],capture_output=True,text=True,timeout=15)
            self.assertEqual(p.returncode,0,p.stderr);return p.stdout
        remote=self.root/'remote.git';run('init','--bare','--initial-branch=main',remote)
        a=self.root/'sender';b=self.root/'receiver'
        for clone in [a,b]:
            run('clone',remote,clone);run('-C',clone,'config','user.name','Test');run('-C',clone,'config','user.email','test@example.invalid')
        (a/'seed.txt').write_text('synthetic seed');run('-C',a,'add','seed.txt');run('-C',a,'commit','-m','seed');run('-C',a,'push','origin','main')
        msg,paths=m.send(a,'gpai','dsh-sd','offline catchup','synthetic','offline-1');m.publish(a,paths)
        self.assertFalse((b/'inbox').exists())
        m.sync(b);report,paths=m.scan(b,'dsh-sd',True)
        # Receipt exists only locally, model a crash before publication.
        self.assertNotIn('received',m.scan(a,'gpai')[0]['outgoing'][0]['events'])
        with contextlib.redirect_stdout(io.StringIO()):m.watch(b,'dsh-sd',30,1)
        m.sync(a);self.assertIn('received',m.scan(a,'gpai')[0]['outgoing'][0]['events'])
        # A new clone sees exactly one receipt, no lost message and no extra ACK.
        c=self.root/'restarted';run('clone',remote,c)
        report,paths=m.scan(c,'dsh-sd',True);self.assertEqual(paths,[])
        self.assertEqual(report['incoming'][0]['id'],msg['id'])
    def test_10_does_not_commit_other_staged_work(self):
        subprocess.run(['git','init','--initial-branch=main',str(self.root)],capture_output=True,check=True)
        (self.root/'someone-else.txt').write_text('do not commit')
        subprocess.run(['git','-C',str(self.root),'add','someone-else.txt'],check=True)
        a,paths=self.send()
        with self.assertRaisesRegex(RuntimeError,'unrelated_staged'):m.publish(self.root,paths)

if __name__=='__main__':unittest.main(verbosity=2)
