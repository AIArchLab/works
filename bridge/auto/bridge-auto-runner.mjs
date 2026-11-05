// BRIDGE-AUTO-01 Runner — managed scheduling script (v2: valid protocol envelope)
// Replicates protocol/mailbox.py send() envelope so GPAI read_message() validates.
// Configuration loaded from bridge-auto-config.json (local, token not committed).
//
// Usage: node bridge-auto-runner.mjs [--round N] [--config config.json]
// Each round:
//   1. Generate unique marker
//   2. Create task in gpai inbox via GitHub API with valid envelope (id=sha256(sender,to,key)[:32], sha256 over canonical payload)
//   3. Send BRIDGE-AUTO message to GPAI via CDP (port from config)
//   4. Poll repo for GPAI response with matching marker
//   5. Record round result (status: completed | blocked_protocol | failed_timeout)

import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import https from 'https';
import http from 'http';
import crypto from 'crypto';

const __dirname = dirname(fileURLToPath(import.meta.url));
const CONFIG_PATH = process.argv.includes('--config')
  ? process.argv[process.argv.indexOf('--config') + 1]
  : join(__dirname, 'bridge-auto-config.json');

let config = {};
if (existsSync(CONFIG_PATH)) {
  config = JSON.parse(readFileSync(CONFIG_PATH, 'utf8'));
}
const GITHUB_TOKEN = process.env.GITHUB_TOKEN || config.github_token || '';
const REPO = config.repo || 'AIArchLab/works';
const CDP_PORT = config.cdp_port || 0;
const GPAI_TAB_URL_PATTERN = config.gpai_tab_url_pattern || 'gpai.app/chat';
const POLL_INTERVAL_MS = config.poll_interval_ms || 10000;
const POLL_TIMEOUT_MS = config.poll_timeout_ms || 300000;
const LOG_DIR = config.log_dir || join(__dirname, 'bridge-auto-logs');
const SENDER = 'dsh-sd';
const RECIPIENT = 'gpai';

if (!CDP_PORT) { console.error('CDP_PORT not configured'); process.exit(1); }
if (!GITHUB_TOKEN) { console.error('GITHUB_TOKEN not configured'); process.exit(1); }
if (!existsSync(LOG_DIR)) mkdirSync(LOG_DIR, { recursive: true });

function log(msg) {
  const ts = new Date().toISOString();
  const line = '[' + ts + '] ' + msg;
  console.log(line);
  const logFile = join(LOG_DIR, 'runner-' + new Date().toISOString().split('T')[0] + '.log');
  try { writeFileSync(logFile, line + '\n', { flag: 'a' }); } catch (e) {}
}

function canonical(x) { return JSON.stringify(x, Object.keys(x).sort(), (k,v)=>v, 2).replace(/\s/g,''); }
// canonical: sorted keys, compact separators, ensure_ascii false
function canon(obj) {
  const keys = Object.keys(obj).sort();
  const o = {};
  for (const k of keys) o[k] = obj[k];
  return JSON.stringify(o, (k,v) => (typeof v === 'string' ? v : v), 0)
    .replace(/,(?=")/g,',').replace(/:(?=")/g,':');
}
// Simpler robust canonical: use a recursive sorter
function canonicalize(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(canonicalize).join(',') + ']';
  const keys = Object.keys(value).sort();
  return '{' + keys.map(k => JSON.stringify(k) + ':' + canonicalize(value[k])).join(',') + '}';
}
function sha256hex(s) { return crypto.createHash('sha256').update(s, 'utf8').digest('hex'); }

function ghApi(method, path, body = null) {
  return new Promise((resolve, reject) => {
    const options = {
      hostname: 'api.github.com',
      path: path,
      method: method,
      headers: {
        'Authorization': 'Bearer ' + GITHUB_TOKEN,
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'bridge-auto-runner/2.0',
        'Content-Type': 'application/json'
      }
    };
    const req = https.request(options, (res) => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => {
        try { resolve({ status: res.statusCode, data: JSON.parse(d) }); }
        catch (e) { resolve({ status: res.statusCode, data: d }); }
      });
    });
    req.on('error', reject);
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

function cdpGetTabs() {
  return new Promise((resolve, reject) => {
    http.get('http://127.0.0.1:' + CDP_PORT + '/json/list', (res) => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => { try { resolve(JSON.parse(d)); } catch (e) { reject(e); } });
    }).on('error', reject);
  });
}

async function findGpaiTab() {
  const tabs = await cdpGetTabs();
  return tabs.find(t => t.type === 'page' && t.url.includes(GPAI_TAB_URL_PATTERN));
}

function cdpConnect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let msgId = 0;
    const pending = new Map();
    ws.onopen = () => resolve({ ws, send: (method, params = {}) => {
      return new Promise((res, rej) => {
        const id = ++msgId;
        pending.set(id, { res, rej });
        ws.send(JSON.stringify({ id, method, params }));
        setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error('CDP timeout: ' + method)); } }, 30000);
      });
    }, pending });
    ws.onerror = (e) => reject(e);
  });
}

async function sendToGpai(message) {
  const tab = await findGpaiTab();
  if (!tab) throw new Error('No GPAI tab found');
  const conn = await cdpConnect(tab.webSocketDebuggerUrl);
  const { ws, send, pending } = conn;
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id).res(msg); pending.delete(msg.id); }
  };
  await send('Runtime.enable');
  await new Promise(r => setTimeout(r, 2000));

  const insertExpr = '(function() { var input = document.querySelector("#message"); if (!input) return "no input"; input.focus(); document.execCommand("selectAll", false, null); document.execCommand("delete", false, null); var ok = document.execCommand("insertText", false, ' + JSON.stringify(message) + '); return "inserted: " + ok + " len=" + input.textContent.length; })()';
  const r1 = await send('Runtime.evaluate', { expression: insertExpr, returnByValue: true });
  log('CDP insert result: ' + (r1.result && r1.result.result ? r1.result.result.value : 'unknown'));

  let sendBtnReady = false;
  for (let i = 0; i < 10; i++) {
    const checkExpr = "(function() { var btn = document.querySelector('button[aria-label=\"送出\"]'); return btn ? (btn.disabled ? 'disabled' : 'ready') : 'missing'; })()";
    const checkR = await send('Runtime.evaluate', { expression: checkExpr, returnByValue: true });
    const status = checkR.result && checkR.result.result ? checkR.result.result.value : 'unknown';
    if (status === 'ready') { sendBtnReady = true; break; }
    log('Send button status: ' + status + ', waiting...');
    await new Promise(r => setTimeout(r, 500));
  }
  if (!sendBtnReady) throw new Error('Send button not ready after 5s');

  const clickExpr = "(function() { var btn = document.querySelector('button[aria-label=\"送出\"]'); if (!btn) return 'no send button'; if (btn.disabled) return 'disabled'; btn.click(); return 'clicked'; })()";
  const r2 = await send('Runtime.evaluate', { expression: clickExpr, returnByValue: true });
  log('CDP click result: ' + (r2.result && r2.result.result ? r2.result.result.value : 'unknown'));

  let inputCleared = false;
  for (let i = 0; i < 10; i++) {
    const lenR = await send('Runtime.evaluate', { expression: 'document.querySelector("#message")?.textContent?.length || 0', returnByValue: true });
    const len = lenR.result && lenR.result.result ? lenR.result.result.value : -1;
    if (len === 0) { inputCleared = true; break; }
    await new Promise(r => setTimeout(r, 500));
  }
  const finalLenR = await send('Runtime.evaluate', { expression: 'document.querySelector("#message")?.textContent?.length || 0', returnByValue: true });
  const inputLen = finalLenR.result && finalLenR.result.result ? finalLenR.result.result.value : -1;
  log('Input length after send: ' + inputLen);
  ws.close();
  if (!inputCleared) throw new Error('Message may not have been sent (input not cleared, len=' + inputLen + ')');
  return { tabId: tab.id, tabUrl: tab.url };
}

function generateMarker(round) {
  const ts = Date.now().toString(36);
  const rand = Math.random().toString(36).substring(2, 8);
  return 'BRIDGE-AUTO-01-R' + round + '-' + ts + '-' + rand;
}

async function createGpaiTask(marker) {
  const key = marker;
  const mid = sha256hex(canonicalize({ sender: SENDER, to: RECIPIENT, key: key })).slice(0, 32);
  const subject = 'BRIDGE-AUTO-01 Round task: ' + marker;
  const body = 'BRIDGE-AUTO-01: 請掃描 AIArchLab/works 的 gpai inbox，處理帶標記 ' + marker + ' 的任務，並將本次唯一標記寫回 repo (bridge/wake-tests/ 或 inbox/dsh-sd/)。\n\n唯一標記：' + marker;
  const payload = {
    protocol: 'aiarchlab.peer-message/1',
    id: mid,
    from: SENDER,
    to: RECIPIENT,
    subject: subject,
    body: body,
    idempotency_key: key,
    reply_to: null,
    references: []
  };
  // check existence for idempotency
  const existing = await ghApi('GET', '/repos/' + REPO + '/contents/inbox/' + RECIPIENT + '/' + mid + '.json');
  if (existing.status === 200 && existing.data.content) {
    const content = Buffer.from(existing.data.content, 'base64').toString('utf8');
    let old;
    try { old = JSON.parse(content); } catch(e) { old = null; }
    if (old) {
      const oldSha = old.sha256;
      // verify digest
      const oldNoSha = Object.assign({}, old); delete oldNoSha.sha256;
      const recomputed = sha256hex(canonicalize(oldNoSha));
      if (recomputed !== oldSha) {
        log('WARNING: existing envelope digest mismatch for ' + mid);
      }
      // idempotency: same payload fields?
      let same = true;
      for (const k of Object.keys(payload)) { if (old[k] !== payload[k]) { same = false; break; } }
      if (same) {
        log('Task already exists with same payload: ' + mid + ' (idempotent reuse)');
        return { taskId: mid, marker, mid, reused: true };
      } else {
        throw new Error('idempotency_key_reused with changed payload for ' + mid);
      }
    }
  }
  payload.created_at = new Date().toISOString();
  payload.sha256 = sha256hex(canonicalize(payload));
  // size guard
  if (Buffer.byteLength(canonicalize(payload), 'utf8') > 262144) throw new Error('message too large');
  const r = await ghApi('PUT', '/repos/' + REPO + '/contents/inbox/' + RECIPIENT + '/' + mid + '.json', {
    message: 'BRIDGE-AUTO-01: create task ' + marker,
    content: Buffer.from(JSON.stringify(payload, null, 2)).toString('base64')
  });
  log('Created gpai task: ' + mid + ' (status ' + r.status + ') marker=' + marker);
  if (r.status !== 201 && r.status !== 200) {
    throw new Error('Failed to create task: HTTP ' + r.status + ' ' + JSON.stringify(r.data).slice(0,200));
  }
  return { taskId: mid, marker, mid, reused: false };
}

async function pollForResponse(marker, timeoutMs) {
  const startTime = Date.now();
  while (Date.now() - startTime < timeoutMs) {
    // inbox/dsh-sd
    const r = await ghApi('GET', '/repos/' + REPO + '/contents/inbox/dsh-sd');
    if (r.status === 200 && Array.isArray(r.data)) {
      for (const item of r.data) {
        if (!item.name.endsWith('.json')) continue;
        const fr = await ghApi('GET', '/repos/' + REPO + '/contents/inbox/dsh-sd/' + item.name);
        if (fr.status === 200 && fr.data.content) {
          const content = Buffer.from(fr.data.content, 'base64').toString('utf8');
          if (content.includes(marker)) {
            log('Found GPAI response with marker ' + marker + ' in ' + item.name);
            let parsed;
            try { parsed = JSON.parse(content); } catch(e) { parsed = content; }
            return { file: item.name, content: parsed };
          }
        }
      }
    }
    // bridge/wake-tests
    const r2 = await ghApi('GET', '/repos/' + REPO + '/contents/bridge/wake-tests');
    if (r2.status === 200 && Array.isArray(r2.data)) {
      for (const item of r2.data) {
        if (item.name.includes(marker)) {
          const fr = await ghApi('GET', '/repos/' + REPO + '/contents/bridge/wake-tests/' + item.name);
          if (fr.status === 200 && fr.data.content) {
            const content = Buffer.from(fr.data.content, 'base64').toString('utf8');
            log('Found wake-test result with marker ' + marker + ' in ' + item.name);
            let parsed;
            try { parsed = JSON.parse(content); } catch(e) { parsed = content; }
            return { file: item.name, content: parsed };
          }
        }
      }
    }
    log('Polling for response to ' + marker + '... (' + Math.round((Date.now()-startTime)/1000) + 's elapsed)');
    await new Promise(r => setTimeout(r, POLL_INTERVAL_MS));
  }
  throw new Error('Timeout waiting for GPAI response to ' + marker);
}

function protocolFailed(resp) {
  const text = (typeof resp === 'string') ? resp : JSON.stringify(resp || '');
  return /protocol_validation\s*=\s*failed/i.test(text) || /缺\s*sha256/.test(text) || /缺 sha256/.test(text);
}

async function runRound(roundNum) {
  log('=== Starting Round ' + roundNum + ' ===');
  const marker = generateMarker(roundNum);
  log('Marker: ' + marker);

  let taskInfo;
  try {
    taskInfo = await createGpaiTask(marker);
  } catch (e) {
    log('BLOCKED: task creation failed: ' + e.message);
    const rr = { round: roundNum, marker, status: 'blocked_task_create', error: e.message, completed_at: new Date().toISOString() };
    writeFileSync(join(LOG_DIR, 'round-' + roundNum + '-' + marker + '.json'), JSON.stringify(rr, null, 2));
    throw e;
  }
  log('Task created: ' + taskInfo.taskId + ' (reused=' + taskInfo.reused + ')');

  let cdpResult;
  try {
    const message = 'BRIDGE-AUTO-01 Round ' + roundNum + ': 請掃描 AIArchLab/works 的 gpai inbox，處理帶標記 ' + marker + ' 的任務，並將本次唯一標記寫回 repo。\n\n唯一標記：' + marker;
    cdpResult = await sendToGpai(message);
    log('CDP send result: ' + JSON.stringify(cdpResult));
  } catch (e) {
    log('BLOCKED: CDP send failed: ' + e.message);
    const rr = { round: roundNum, marker, taskId: taskInfo.taskId, status: 'blocked_cdp', error: e.message, completed_at: new Date().toISOString() };
    writeFileSync(join(LOG_DIR, 'round-' + roundNum + '-' + marker + '.json'), JSON.stringify(rr, null, 2));
    throw e;
  }

  let response;
  try {
    response = await pollForResponse(marker, POLL_TIMEOUT_MS);
  } catch (e) {
    log('FAILED: poll timeout: ' + e.message);
    const rr = { round: roundNum, marker, taskId: taskInfo.taskId, cdpResult, status: 'failed_timeout', error: e.message, completed_at: new Date().toISOString() };
    writeFileSync(join(LOG_DIR, 'round-' + roundNum + '-' + marker + '.json'), JSON.stringify(rr, null, 2));
    throw e;
  }
  log('GPAI response received: ' + JSON.stringify(response.content).substring(0, 300));

  const pf = protocolFailed(response.content);
  const status = pf ? 'blocked_protocol' : 'completed';
  if (pf) log('ROUND ' + roundNum + ' BLOCKED: GPAI reported protocol_validation=failed (sha256/envelope). Not creating new marker for this failure.');
  else log('Round ' + roundNum + ' protocol OK.');

  const roundResult = {
    round: roundNum,
    marker: marker,
    taskId: taskInfo.taskId,
    envelope_id: taskInfo.mid,
    cdpResult: cdpResult,
    responseFile: response.file,
    protocol_failed: pf,
    completed_at: new Date().toISOString(),
    status: status
  };
  const resultFile = join(LOG_DIR, 'round-' + roundNum + '-' + marker + '.json');
  writeFileSync(resultFile, JSON.stringify(roundResult, null, 2));
  log('Round ' + roundNum + ' result saved to ' + resultFile);
  log('=== Round ' + roundNum + ' finished with status=' + status + ' ===');
  return roundResult;
}

async function main() {
  const roundArg = process.argv.includes('--round') ? parseInt(process.argv[process.argv.indexOf('--round') + 1]) : null;
  if (roundArg) {
    await runRound(roundArg);
  } else {
    const r1 = await runRound(1);
    if (r1.status === 'blocked_protocol') {
      log('Round 1 blocked on protocol; pausing before round 2 per GPAI guidance (no new marker masking).');
    }
    log('Waiting 60 seconds before round 2...');
    await new Promise(r => setTimeout(r, 60000));
    const r2 = await runRound(2);
    log('=== All rounds finished ===');
    log('Round 1: ' + r1.marker + ' -> ' + r1.status);
    log('Round 2: ' + r2.marker + ' -> ' + r2.status);
  }
}

main().catch(e => {
  log('FATAL ERROR: ' + e.message);
  if (e.stack) log(e.stack);
  process.exit(1);
});
