#!/usr/bin/env python3
"""One-command real Python -> Node handoff, no model or cloud credential needed."""
import base64,hashlib,json,os,subprocess,sys,tempfile,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT/'sdk'))
from server import serve
from python_client import Client

def main():
    import secrets,shutil
    if not shutil.which('node'):raise SystemExit('Node.js 18+ required for the cross-runtime demo; broker and dashboard require Python only.')
    a,b=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory() as folder:
        server=serve('127.0.0.1',0,str(Path(folder)/'state.db'),{a:{'tenant':'demo','actor':'python','role':'worker'},b:{'tenant':'demo','actor':'node','role':'worker'}})
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url='http://127.0.0.1:'+str(server.server_port);c=Client(url,a)
            task=c.call('',{'state':{'steps':['python-checkpoint'],'goal':'Resume in another runtime'}});tid=task['id'];lease=c.call('/'+tid+'/acquire',{})
            raw='Python checkpoint — 繁體中文'.encode();c.call('/'+tid+'/write',{**lease,'revision':0,'state':task['state'],'artifacts':[{'name':'checkpoint.txt','base64':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest()}]})
            h=c.call('/'+tid+'/prepare',{**lease,'revision':1,'summary':'Verify the attachment, ACK, then append node-resumed.'})
            print('Python checkpoint saved; source writes are frozen.',flush=True)
            target=subprocess.run(['node',str(ROOT/'examples/node_target.mjs'),url,tid,h['handoff_id'],h['sha256']],env={**os.environ,'RH_TARGET_KEY':b},capture_output=True,text=True,timeout=25)
            if target.returncode:raise RuntimeError(target.stderr)
            result=json.loads(target.stdout)
            from urllib.error import HTTPError
            try:c.call('/'+tid+'/write',{**lease,'revision':2,'state':{'invalid':'stale write'}})
            except HTTPError as e:
                if e.code!=409:raise
                result['stale_source_rejected']=True
            else:raise RuntimeError('stale source was accepted')
            result['audit_events']=len(c.call('/'+tid+'/events')['events'])
            output=ROOT/'demo_receipt.json';output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
            print(json.dumps(result,ensure_ascii=False,indent=2));print('Receipt: '+str(output))
        finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':main()
