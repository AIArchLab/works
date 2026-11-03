import {randomUUID,createHash} from 'node:crypto';
export class Client {
  constructor(url,key){this.url=url.replace(/\/$/,'');this.key=key;}
  async call(path,body,key){
    const headers={Authorization:`Bearer ${this.key}`};
    if(body!==undefined){headers['Content-Type']='application/json';headers['Idempotency-Key']=key||randomUUID();}
    const response=await fetch(this.url+'/v1/tasks'+path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(15000)});
    const data=await response.json();if(!response.ok)throw new Error(`${response.status}: ${data.error}`);return data;
  }
  async bundle(task,expected){
    const envelope=await this.call(`/${task}/bundle`);
    const raw=Buffer.from(envelope.bundle_base64,'base64');
    const sha=createHash('sha256').update(raw).digest('hex');
    if(sha!==envelope.sha256||(expected&&sha!==expected))throw new Error('bundle_digest_mismatch');
    const bundle=JSON.parse(raw.toString('utf8'));
    if(bundle.protocol!=='relayhandoff/1'||bundle.task_id!==task)throw new Error('bundle_identity_mismatch');
    for(const a of Object.values(bundle.artifacts))if(createHash('sha256').update(Buffer.from(a.base64,'base64')).digest('hex')!==a.sha256)throw new Error('artifact_digest_mismatch');
    return {envelope,bundle};
  }
}
