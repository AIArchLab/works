"""Uses the shipped handoff workflow to verify this real release, not a toy task."""
import base64,hashlib,json,os,secrets,subprocess,sys,tempfile,threading
from pathlib import Path
ROOT=Path(__file__).parent.resolve();sys.path.insert(0,str(ROOT/'sdk'))
from server import serve
from python_client import Client
excluded={'MANIFEST.sha256.json','release_handoff_receipt.json','demo_receipt.json'}
manifest={str(p.relative_to(ROOT)).replace(os.sep,'/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.rglob('*')) if p.is_file() and not any(x in p.parts for x in ['__pycache__','.runtime','.git']) and p.name not in excluded}
(ROOT/'MANIFEST.sha256.json').write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2))
a,b=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
with tempfile.TemporaryDirectory() as folder:
 server=serve('127.0.0.1',0,str(Path(folder)/'state.db'),{a:{'tenant':'release','actor':'builder','role':'worker'},b:{'tenant':'release','actor':'node-reviewer','role':'worker'}})
 t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
 try:
  url='http://127.0.0.1:'+str(server.server_port);c=Client(url,a)
  task=c.call('',{'state':{'product':'RelayHandoff','version':'0.1.0','stage':'built','acceptance':'Verify all candidate source file hashes before ACK.'}});tid=task['id'];l=c.call('/'+tid+'/acquire',{})
  raw=json.dumps(manifest,ensure_ascii=False,sort_keys=True).encode();c.call('/'+tid+'/write',{**l,'revision':0,'state':task['state'],'artifacts':[{'name':'release-manifest.json','base64':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest()}]})
  h=c.call('/'+tid+'/prepare',{**l,'revision':1,'summary':'Review actual release source bytes using the operator-supplied local root. ACK only after all hashes match.'})
  p=subprocess.run(['node',str(ROOT/'examples/release_target.mjs'),url,tid,h['handoff_id'],h['sha256'],str(ROOT)],env={**os.environ,'RH_TARGET_KEY':b},capture_output=True,text=True,timeout=30)
  if p.returncode:raise RuntimeError(p.stderr)
  receipt=json.loads(p.stdout);state=c.call('/'+tid)
  if state['state']['stage']!='verified_by_node':raise RuntimeError('target did not checkpoint')
  e=state['outputs']['verification-receipt.json'];raw=base64.b64decode(e['base64']);assert hashlib.sha256(raw).hexdigest()==e['sha256']
  receipt['receipt_readback_verified']=True;receipt['audit_event_count']=len(c.call('/'+tid+'/events')['events'])
  (ROOT/'release_handoff_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2));print(json.dumps(receipt,ensure_ascii=False))
 finally:server.shutdown();server.server_close();t.join()
