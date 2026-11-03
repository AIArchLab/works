import {randomUUID,createHash} from 'node:crypto';
export function validate(value,depth=0,active=new Set()) {
  if(depth>64)throw Error('json_depth_exceeded');
  if(value===null||typeof value==='boolean')return value;
  if(typeof value==='number'){
    if(!Number.isFinite(value))throw Error('json_non_finite_number');
    if(Math.abs(value)>Number.MAX_SAFE_INTEGER)throw Error('json_number_out_of_range');
    return value;
  }
  if(typeof value==='string'){
    for(let i=0;i<value.length;i++){
      const ch=value.charCodeAt(i);
      if(ch>=0xD800&&ch<=0xDBFF){const next=value.charCodeAt(++i);if(!(next>=0xDC00&&next<=0xDFFF))throw Error('json_invalid_unicode');}
      else if(ch>=0xDC00&&ch<=0xDFFF)throw Error('json_invalid_unicode');
    }
    return value;
  }
  if(typeof value!=='object'||(!Array.isArray(value)&&Object.getPrototypeOf(value)!==Object.prototype&&Object.getPrototypeOf(value)!==null))throw Error('json_unsupported_type');
  if(active.has(value))throw Error('json_cycle');active.add(value);
  if(Array.isArray(value)){for(const item of value)validate(item,depth+1,active);}
  else for(const [key,item] of Object.entries(value)){validate(key,depth+1,active);validate(item,depth+1,active);}
  active.delete(value);return value;
}
export class Client {
  constructor(url,key){this.url=url.replace(/\/$/,'');this.key=key;}
  async call(path,body,key){
    if(body!==undefined)validate(body);
    const headers={Authorization:`Bearer ${this.key}`};
    if(body!==undefined){headers['Content-Type']='application/json';headers['Idempotency-Key']=key||randomUUID();}
    const response=await fetch(this.url+'/v1/tasks'+path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(15000)});
    const data=await response.json();validate(data);if(!response.ok)throw new Error(`${response.status}: ${data.error}`);return data;
  }
  async bundle(task,expected){
    const envelope=await this.call(`/${task}/bundle`);
    const raw=Buffer.from(envelope.bundle_base64,'base64');
    const sha=createHash('sha256').update(raw).digest('hex');
    if(sha!==envelope.sha256||(expected&&sha!==expected))throw new Error('bundle_digest_mismatch');
    const bundle=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));validate(bundle);
    if(bundle.protocol!=='relayhandoff/1'||bundle.task_id!==task)throw new Error('bundle_identity_mismatch');
    for(const a of Object.values(bundle.artifacts))if(createHash('sha256').update(Buffer.from(a.base64,'base64')).digest('hex')!==a.sha256)throw new Error('artifact_digest_mismatch');
    return {envelope,bundle};
  }
}
