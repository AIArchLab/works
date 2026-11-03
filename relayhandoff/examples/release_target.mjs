import {Client} from '../sdk/node_client.mjs';
import {readFile} from 'node:fs/promises';
import {resolve,sep} from 'node:path';
import {createHash} from 'node:crypto';
const [url,task,id,sha,rootArg]=process.argv.slice(2);const root=resolve(rootArg);
const c=new Client(url,process.env.RH_TARGET_KEY);const claim=await c.call(`/${task}/claim`,{handoff_id:id});
const {envelope,bundle}=await c.bundle(task,sha);if(envelope.handoff_id!==id||claim.sha256!==sha)throw Error('handoff_identity_mismatch');
if(!bundle.state||typeof bundle.state.product!=='string'||typeof bundle.state.version!=='string'||bundle.state.stage!=='built')throw Error('missing_required_state');
if(!bundle.artifacts?.['release-manifest.json'])throw Error('missing_required_attachment');
const manifest=JSON.parse(Buffer.from(bundle.artifacts['release-manifest.json'].base64,'base64').toString('utf8'));
if(!manifest||Array.isArray(manifest)||typeof manifest!=='object'||Object.keys(manifest).length===0)throw Error('invalid_manifest');
for(const [name,expected] of Object.entries(manifest)){
 if(typeof expected!=='string'||!(/^[a-f0-9]{64}$/).test(expected))throw Error('invalid_manifest_digest');
 const path=resolve(root,name);if(!path.startsWith(root+sep))throw Error('unsafe_manifest_path');
 const bytes=await readFile(path);if(createHash('sha256').update(bytes).digest('hex')!==expected)throw Error('source_digest_mismatch: '+name);
}
await c.call(`/${task}/ack`,{...claim,sha256:sha});
const receipt={verified_files:Object.keys(manifest).length,runtime:process.version,bundle_sha256:sha,task_id:task,epoch:claim.epoch,verification:'actual source bytes checked by independent Node process'};
const bytes=Buffer.from(JSON.stringify(receipt));
await c.call(`/${task}/write`,{...claim,revision:bundle.revision,state:{...bundle.state,stage:'verified_by_node'},artifacts:[{name:'verification-receipt.json',base64:bytes.toString('base64'),sha256:createHash('sha256').update(bytes).digest('hex')}]});
console.log(JSON.stringify(receipt));
