"""Transport-neutral caller SDK; runtime remains responsible for safe step boundaries."""
import base64,hashlib,json,uuid,urllib.request,urllib.error
try:
    from .portable_json import validate
except ImportError:
    from portable_json import validate

class Client:
    def __init__(self,url,key): self.url=url.rstrip('/');self.key=key
    def call(self,path,body=None,key=None):
        if body is not None: validate(body)
        headers={'Authorization':'Bearer '+self.key}
        if body is not None:
            headers.update({'Content-Type':'application/json','Idempotency-Key':key or str(uuid.uuid4())})
        req=urllib.request.Request(self.url+'/v1/tasks'+path,data=None if body is None else json.dumps(body,allow_nan=False).encode(),headers=headers)
        with urllib.request.urlopen(req,timeout=15) as response:
            value=json.load(response)
            validate(value)
            return value
    def bundle(self,task_id,expected_sha=None):
        envelope=self.call('/'+task_id+'/bundle')
        raw=base64.b64decode(envelope['bundle_base64'],validate=True)
        sha=hashlib.sha256(raw).hexdigest()
        if sha!=envelope['sha256'] or (expected_sha is not None and sha!=expected_sha):raise ValueError('bundle_digest_mismatch')
        b=json.loads(raw)
        validate(b)
        if b['protocol']!='relayhandoff/1' or b['task_id']!=task_id:raise ValueError('bundle_identity_mismatch')
        for artifact in b['artifacts'].values():
            if hashlib.sha256(base64.b64decode(artifact['base64'],validate=True)).hexdigest()!=artifact['sha256']:raise ValueError('artifact_digest_mismatch')
        return envelope,b
