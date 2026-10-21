"""Synthetic scenario; --live uses a real configured model, default is an explicit test double."""
import argparse, datetime, json, os, pathlib, secrets, sqlite3, subprocess, sys, tempfile, threading, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from taskloop.agents import RemoteAgent
from taskloop.core import Store,Engine,Network
from taskloop.receiver import server

class DemoAgent:
    def __init__(self):self.actions=[];self.usage=[]
    def decide(self,spec,observation):
        action='inspect' if observation is None else 'report';self.actions.append(action)
        return {'action':action,'summary':'Synthetic demo: observed HTTP '+str(observation['status'])} if observation is not None else {'action':action}

def main():
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--output',type=pathlib.Path);x=p.parse_args()
    secret=secrets.token_hex(32)
    with tempfile.TemporaryDirectory() as td:
        td=pathlib.Path(td);inbox=td/'inbox.sqlite3';taskdb=td/'tasks.sqlite3';receiver=server('127.0.0.1',0,inbox,secret,fail_first=1)
        thread=threading.Thread(target=receiver.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(receiver.server_address[1])
        try:
            s=Store(taskdb);agent=RemoteAgent() if x.live else DemoAgent();e=Engine(s,agent,Network(['127.0.0.1'],True),secret,retry_base=0.1)
            due=time.time()+0.1;s.submit('synthetic-check',base+'/health',base+'/inbox',due)
            assert not e.execute_one(due-1)
            time.sleep(0.15);e.execute_one();e.deliver_one();before=s.status('synthetic-check');assert before['state']=='AWAITING_DELIVERY';s.db.close()
            time.sleep(0.15)
            if x.live:
                env=os.environ.copy();env['TASKLOOP_WEBHOOK_SECRET']=secret
                result=subprocess.run([sys.executable,'-m','taskloop','--db',str(taskdb),'worker','--once','--allow-host','127.0.0.1','--allow-local-demo'],env=env,cwd=pathlib.Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=30)
                assert result.returncode==0,result.stderr
                s=Store(taskdb)
            else:
                s=Store(taskdb);e=Engine(s,DemoAgent(),Network(['127.0.0.1'],True),secret);assert not e.execute_one();e.deliver_one()
            after=s.status('synthetic-check');assert after['state']=='COMPLETED'
            with sqlite3.connect(inbox) as db:received=db.execute('SELECT count(*) FROM inbox').fetchone()[0]
            report={'scenario':'Synthetic local HTTP endpoint and durable signed recipient inbox','agent':'real remote model' if x.live else 'explicit deterministic test double','ran_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'actions':agent.actions,'http_gets':receiver.inspections,'notification_requests':receiver.delivery_requests,'state_after_first_503':before['state'],'final_state':after['state'],'receiver_unique_events':received,'delivery_attempts':after['delivery']['attempts'],'resumed_in_new_process':bool(x.live),'valid_signed_receipt':bool(after['delivery']['receipt']),'usage':agent.usage,'human_read_receipt':False}
            assert receiver.inspections==1 and receiver.delivery_requests==2 and received==1
            if x.output:x.output.parent.mkdir(parents=True,exist_ok=True);x.output.write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps(report,indent=2));s.db.close()
        finally:receiver.shutdown();thread.join();receiver.server_close()
if __name__=='__main__':main()
