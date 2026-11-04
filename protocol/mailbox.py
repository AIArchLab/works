#!/usr/bin/env python3
"""Repo mailbox v1: durable envelopes, receiver receipts, replayable scans.
No model invocation, no credential storage, no implicit git add or agent wake.
"""
import argparse,datetime,hashlib,json,os,re,subprocess,time,uuid
from pathlib import Path
VERSION='aiarchlab.peer-message/1'
EVENTS={'received','accepted','blocked','completed','rejected','verified'}

def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(x):return hashlib.sha256(canonical(x)).hexdigest()
def member(x):
    if not isinstance(x,str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}',x):raise ValueError('invalid_member')
    return x
def identifier(x):
    if not isinstance(x,str) or not re.fullmatch(r'[a-f0-9]{32}',x):raise ValueError('invalid_message_id')
    return x
def write_once(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);raw=canonical(value)+b'\n'
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8'))!=value:raise ValueError('immutable_record_conflict')
        return False
    temp=path.parent/('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with open(temp,'xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        try:os.link(temp,path)
        except FileExistsError:
            if json.loads(path.read_text(encoding='utf-8'))!=value:raise ValueError('immutable_record_conflict')
            return False
        if os.name=='posix':
            fd=os.open(str(path.parent),os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
        return True
    finally:
        if temp.exists():temp.unlink()

def read_message(path):
    if path.is_symlink():raise ValueError('symlink_not_allowed')
    if path.stat().st_size>262144:raise ValueError('message_too_large')
    d=json.loads(path.read_text(encoding='utf-8'));expected=d.pop('sha256')
    if sha(d)!=expected:raise ValueError('message_digest_mismatch')
    d['sha256']=expected
    if d.get('protocol')!=VERSION:raise ValueError('unknown_protocol')
    identifier(d['id']);member(d['from']);member(d['to'])
    if path.name!=d['id']+'.json' or path.parent.name!=d['to']:raise ValueError('message_path_mismatch')
    stamp=datetime.datetime.fromisoformat(d['created_at'])
    if stamp.tzinfo is None:raise ValueError('timezone_required')
    return d

def messages(root,errors=None):
    out=[]
    for path in sorted((root/'inbox').glob('*/*.json')):
        try:out.append(read_message(path))
        except (ValueError,KeyError,TypeError,OSError) as e:
            if errors is None:raise
            errors.append({'path':str(path.relative_to(root)),'error':str(e)})
    return out

def find(root,mid):
    identifier(mid);hits=list((root/'inbox').glob('*/'+mid+'.json'))
    if len(hits)!=1:raise ValueError('message_not_found_or_ambiguous')
    return read_message(hits[0])

def send(root,sender,to,subject,body,key,reply_to=None,references=None):
    member(sender);member(to)
    if not subject or not body or not key:raise ValueError('subject_body_key_required')
    if len(subject)>256 or len(body)>100000 or len(key)>256:raise ValueError('message_too_large')
    if reply_to:
        original=find(root,reply_to)
        if original['from']!=to or original['to']!=sender:raise ValueError('reply_route_mismatch')
    mid=sha({'sender':sender,'to':to,'key':key})[:32]
    payload={'protocol':VERSION,'id':mid,'from':sender,'to':to,'subject':subject,'body':body,'idempotency_key':key,'reply_to':reply_to,'references':references or []}
    path=root/'inbox'/to/(mid+'.json')
    if path.exists():
        old=read_message(path)
        if any(old[k]!=v for k,v in payload.items()):raise ValueError('idempotency_key_reused')
        return old,[]
    payload['created_at']=utc();payload['sha256']=sha(payload)
    if len(canonical(payload))>262144:raise ValueError('message_too_large')
    write_once(path,payload);return payload,[path]

def receipts(root,message):
    results=[]
    for path in sorted((root/'inbox/_receipts').glob('*/'+message['id']+'/*.json')):
        r=json.loads(path.read_text(encoding='utf-8'));expected=r.pop('sha256')
        if sha(r)!=expected or r.get('message_sha256')!=message['sha256'] or r.get('message_id')!=message['id']:raise ValueError('receipt_digest_mismatch')
        if r['event'] not in EVENTS:raise ValueError('invalid_receipt_event')
        expected_actor=message['from'] if r['event']=='verified' else message['to']
        if r['actor']!=expected_actor or path.parent.parent.name!=r['actor']:raise ValueError('receipt_actor_mismatch')
        r['sha256']=expected;results.append(r)
    return sorted(results,key=lambda x:(x['created_at'],x['id']))

def record(root,actor,mid,event,detail='',references=None):
    member(actor);m=find(root,mid)
    if event not in EVENTS:raise ValueError('invalid_event')
    if actor!=(m['from'] if event=='verified' else m['to']):raise ValueError('not_receipt_owner')
    refs=references or [];prior=receipts(root,m);types={x['event'] for x in prior}
    if event=='verified' and 'completed' not in types:raise ValueError('completion_required')
    if event in {'accepted','blocked','rejected'} and 'received' not in types:raise ValueError('receipt_required')
    if event=='completed' and 'accepted' not in types:raise ValueError('acceptance_required')
    if event in {'completed','verified'} and not refs:raise ValueError('evidence_reference_required')
    body={'message_id':mid,'message_sha256':m['sha256'],'actor':actor,'event':event,'detail':detail,'references':refs}
    rid=sha(body)[:32];path=root/'inbox/_receipts'/actor/mid/(rid+'.json')
    if path.exists():return json.loads(path.read_text(encoding='utf-8')),[]
    if event!='received' and ('verified' in types or 'rejected' in types):raise ValueError('terminal_state')
    body.update(id=rid,created_at=utc());body['sha256']=sha(body);write_once(path,body)
    return body,[path]

def scan(root,actor,receive=False):
    member(actor);incoming=[];outgoing=[];changed=[];errors=[]
    for m in messages(root,errors):
        if actor not in (m['from'],m['to']):continue
        try:rs=receipts(root,m)
        except (ValueError,KeyError,TypeError,OSError) as e:
            errors.append({'message_id':m['id'],'error':str(e)});continue
        types={r['event'] for r in rs}
        if receive and m['to']==actor and 'received' not in types:
            _,new=record(root,actor,m['id'],'received','Collector persisted this envelope; not an agent acceptance.')
            changed+=new;rs=receipts(root,m);types={r['event'] for r in rs}
        # Never hide unaccepted or unresolved messages behind a time cursor.
        summary={'id':m['id'],'from':m['from'],'to':m['to'],'subject':m['subject'],'sha256':m['sha256'],'events':sorted(types),'closed':bool(types & {'verified','rejected'})}
        age=(datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(m['created_at'])).total_seconds()
        summary['delivery_overdue']=age>300 and 'received' not in types
        summary['acceptance_overdue']=age>900 and not(types & {'accepted','blocked','rejected','completed','verified'})
        if m['to']==actor:incoming.append(summary)
        if m['from']==actor:outgoing.append(summary)
    return {'member':actor,'checked_at':utc(),'incoming':incoming,'outgoing':outgoing,'validation_errors':errors},changed

def git(root,*args):
    p=subprocess.run(['git','-C',str(root),*args],capture_output=True,text=True,timeout=45)
    if p.returncode:raise RuntimeError('git '+args[0]+' failed: '+p.stderr[:1000])
    return p.stdout.strip()

def sync(root):
    # Do not stash/reset another member's work; fail visibly on a dirty tree.
    if git(root,'status','--porcelain','--untracked-files=no'):raise RuntimeError('tracked_worktree_dirty; use a dedicated coordination clone')
    git(root,'pull','--rebase','origin','main')

def publish(root,paths):
    rel=[str(p.relative_to(root)) for p in paths]
    if not rel:return
    staged=git(root,'diff','--cached','--name-only').splitlines()
    if any(p not in rel for p in staged):raise RuntimeError('unrelated_staged_changes; refusing commit')
    git(root,'add','--',*rel)
    if git(root,'diff','--cached','--name-only'):git(root,'commit','-m','peercomm: persist message or receipt')
    # Lost push acknowledgement is safe: records are deterministic and retained locally.
    for attempt in range(3):
        try:git(root,'push','origin','HEAD:main');return
        except RuntimeError:
            if attempt==2:raise
            sync(root)

def actor_paths(root,actor):
    paths=[root/'inbox'/m['to']/(m['id']+'.json') for m in messages(root,[]) if m['from']==actor]
    return paths+list((root/'inbox/_receipts'/actor).glob('*/*.json'))

def watch(root,actor,interval=60,cycles=0):
    if interval<30:raise ValueError('poll_interval_must_be_at_least_30_seconds')
    count=0
    while not cycles or count<cycles:
        count+=1
        try:
            publish(root,actor_paths(root,actor));sync(root)
            report,paths=scan(root,actor,True);publish(root,actor_paths(root,actor))
            print(json.dumps({'ok':True,'cycle':count,**report},ensure_ascii=False),flush=True)
        except Exception as e:
            # Retry queued local records on the next pass, never claim delivery success.
            print(json.dumps({'ok':False,'cycle':count,'error':str(e)},ensure_ascii=False),flush=True)
        if not cycles or count<cycles:time.sleep(interval)

def main():
    p=argparse.ArgumentParser();p.add_argument('--repo',default=str(Path(__file__).resolve().parents[1]));p.add_argument('--member',required=True)
    subs=p.add_subparsers(dest='command',required=True)
    s=subs.add_parser('send');s.add_argument('--to',required=True);s.add_argument('--subject',required=True);s.add_argument('--body-file',required=True);s.add_argument('--key',required=True);s.add_argument('--reply-to');s.add_argument('--publish',action='store_true')
    s=subs.add_parser('scan');s.add_argument('--receive',action='store_true');s.add_argument('--publish',action='store_true')
    s=subs.add_parser('record');s.add_argument('message_id');s.add_argument('event',choices=sorted(EVENTS));s.add_argument('--detail',default='');s.add_argument('--reference',action='append',default=[]);s.add_argument('--publish',action='store_true')
    s=subs.add_parser('show');s.add_argument('message_id')
    s=subs.add_parser('watch');s.add_argument('--interval',type=int,default=60);s.add_argument('--cycles',type=int,default=0)
    subs.add_parser('sync')
    a=p.parse_args();root=Path(a.repo).resolve();member(a.member)
    if a.command=='watch':return watch(root,a.member,a.interval,a.cycles)
    if a.command=='sync':sync(root);return
    if a.command=='show':result=find(root,a.message_id);paths=[]
    elif a.command=='send':result,paths=send(root,a.member,a.to,a.subject,Path(a.body_file).read_text(encoding='utf-8'),a.key,a.reply_to)
    elif a.command=='scan':result,paths=scan(root,a.member,a.receive)
    else:result,paths=record(root,a.member,a.message_id,a.event,a.detail,a.reference)
    if getattr(a,'publish',False):
        # Include previously queued actor-owned records after an earlier local/push failure.
        paths=list(dict.fromkeys(paths+actor_paths(root,a.member)))
        publish(root,paths)
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
