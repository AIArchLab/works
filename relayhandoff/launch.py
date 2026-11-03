#!/usr/bin/env python3
"""One command starts a loopback-only local evaluation instance."""
import argparse,json,os,secrets,threading,webbrowser
from pathlib import Path
from server import serve
p=argparse.ArgumentParser();p.add_argument('--no-browser',action='store_true');p.add_argument('--port',type=int,default=8787);a=p.parse_args()
folder=Path(__file__).parent/'.runtime';folder.mkdir(mode=0o700,exist_ok=True)
config=folder/'keys.json'
if not config.exists():
    keys={secrets.token_urlsafe(32):{'tenant':'local','actor':actor,'role':role} for actor,role in [('operator','worker'),('receiver','worker'),('auditor','reader')]}
    fd=os.open(str(config),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump(keys,f)
keys=json.loads(config.read_text());server=serve('127.0.0.1',a.port,str(folder/'state.db'),keys)
key=next(k for k,v in keys.items() if v['actor']=='operator')
url=f'http://127.0.0.1:{server.server_port}/'
print('RelayHandoff: '+url,flush=True);print('Local private credentials: '+str(config),flush=True)
if not a.no_browser:threading.Timer(.4,lambda:webbrowser.open(url+'#'+key)).start()
try:server.serve_forever()
except KeyboardInterrupt:pass
finally:server.server_close()
