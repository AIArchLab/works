// Receiver process: no Python runtime, no access to broker DB.
import {Client} from '../sdk/node_client.mjs';
const [url,task,handoff,expected]=process.argv.slice(2);
const c=new Client(url,process.env.RH_TARGET_KEY);
const claim=await c.call(`/${task}/claim`,{handoff_id:handoff});
const {envelope,bundle}=await c.bundle(task,expected);
if(envelope.handoff_id!==handoff||claim.sha256!==envelope.sha256)throw new Error('handoff_changed');
await c.call(`/${task}/ack`,{...claim,sha256:envelope.sha256});
const text=Buffer.from(bundle.artifacts['checkpoint.txt'].base64,'base64').toString('utf8');
if(text!=='Python checkpoint — 繁體中文')throw new Error('attachment_not_preserved');
const state={...bundle.state,completed_by:'node',steps:[...bundle.state.steps,'node-resumed']};
const result=await c.call(`/${task}/write`,{...claim,revision:bundle.revision,state});
console.log(JSON.stringify({task_id:task,phase:result.phase,epoch:result.epoch,state:result.state,verified_attachment:true}));
