// ============================================================================
// BRIDGE-AUTO-01: De-identified sender-side runner (submitted to shared repo)
// ============================================================================
// This is the de-identified version of the BRIDGE-AUTO-01 runner.
// Sensitive content (GitHub token, CDP port, Chrome profile path, GPAI session ID)
// has been redacted. The original runner runs on DSH host with local config.
//
// Target conversation: GPAI chat (gpai.app/chat) — session ID redacted
// CDP: loopback only, port redacted
// GitHub: token from local secrets, repo AIArchLab/works
//
// Deployed via: DSH host managed schedule (schedule_create)
// Rounds: 2, interval >= 60s
// ============================================================================

// BRIDGE-AUTO-01 Runner — managed scheduling script
// De-identified: no tokens, no cookies, no CDP internals in source
// Configuration is loaded from environment or config file at runtime
//
// Usage: node bridge-auto-runner.mjs [--round N] [--config config.json]
// Each round:
//   1. Generate unique marker
//   2. Create task in gpai inbox via GitHub API
//   3. Send BRIDGE-AUTO message to GPAI via CDP (port CDP_PORT_FROM_CONFIG)
//   4. Poll repo for GPAI response with matching marker
//   5. Record round result
//
// Prerequisites:
//   - Chrome running with --remote-debugging-port=CDP_PORT_FROM_CONFIG --user-data-dir=<profile>
//   - GPAI conversation open in that Chrome instance
//   - GitHub token in env GITHUB_TOKEN or config file
//   - CDP target tab URL containing gpai.app/chat

import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import https from 'https';
import http from 'http';

const __dirname = dirname(fileURLToPath(import.meta.url));
const CONFIG_PATH = process.argv.includes('--config')
  ? process.argv[process.argv.indexOf('--config') + 1]
  : join(__dirname, 'bridge-auto-config.json');

// Load config
let config = {};
if (existsSync(CONFIG_PATH)) {
  config = JSON.parse(readFileSync(CONFIG_PATH, 'utf8'));
}
const GITHUB_TOKEN = process.env.GITHUB_TOKEN || config.GITHUB_TOKEN_FROM_CONFIG || '';
const REPO = config.repo || 'AIArchLab/works';
const CDP_PORT = config.cdp_port || CDP_PORT_FROM_CONFIG;
const GPAI_TAB_URL_PATTERN = config.gpai_tab_url_pattern || 'gpai.app/chat';
const POLL_INTERVAL_MS = config.poll_interval_ms || 10000;
const POLL_TIMEOUT_MS = config.poll_timeout_ms || 300000;
const LOG_DIR = config.log_dir || join(__dirname, 'bridge-auto-logs');

if (!existsSync(LOG_DIR)) mkdirSync(LOG_DIR, { recursive: true });

function log(msg) {
  const ts = new Date().toISOString();
  const line = `[${ts}] ${msg}`;
  console.log(line);
  const logFile = join(LOG_DIR, `runner-${new Date().toISOString().split('T')[0]}.log`);
  // Append to log file
  try { writeFileSync(logFile, line + '\n', { flag: 'a' }); } catch (e) {}
}

function ghApi(method, path, body = null) {
  return new Promise((resolve, reject) => {
    const options = {
      hostname: 'api.github.com',
      path: path,
      method: method,
      headers: {
        'Authorization': 'Bearer ' + GITHUB_TOKEN,
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'bridge-auto-runner/1.0',
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
    http.get(`http://127.0.0.1:${CDP_PORT}/json/list`, (res) => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => {
        try { resolve(JSON.parse(d)); } catch (e) { reject(e); }
      });
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
  const { ws, send, pending } = await cdpConnect(tab.webSocketDebuggerUrl);
  // Set up message handler
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id).res(msg);
      pending.delete(msg.id);
    }
  };
  await send('Runtime.enable');
  await new Promise(r => setTimeout(r, 1000));
  // Focus input and type
  const expr = `(function() {
    const input = document.querySelector('#message');
    if (!input) return 'no input found';
    input.focus();
    document.execCommand('selectAll', false, null);
    document.execCommand('delete', false, null);
    const ok = document.execCommand('insertText', false, ${JSON.stringify(message)});
    return 'inserted: ' + ok + ' len=' + input.textContent.length;
  })()`;
  const r1 = await send('Runtime.evaluate', { expression: expr, returnByValue: true });
  log('CDP insert result: ' + (r1.result?.result?.value || 'unknown'));
  await new Promise(r => setTimeout(r, 1000));
  // Click send
  const clickExpr = `(function() {
    const btn = document.querySelector('button[aria-label="送出"]');
    if (!btn) return 'no send button';
    btn.click();
    return 'clicked';
  })()`;
  const r2 = await send('Runtime.evaluate', { expression: clickExpr, returnByValue: true });
  log('CDP click result: ' + (r2.result?.result?.value || 'unknown'));
  await new Promise(r => setTimeout(r, 2000));
  // Verify input cleared
  const r3 = await send('Runtime.evaluate', { expression: 'document.querySelector("#message")?.textContent?.length || 0', returnByValue: true });
  const inputLen = r3.result?.result?.value;
  log('Input length after send: ' + inputLen);
  ws.close();
  if (inputLen !== 0) throw new Error('Message may not have been sent (input not cleared)');
  return { tabId: tab.id, tabUrl: tab.url };
}

function generateMarker(round) {
  const ts = Date.now().toString(36);
  const rand = Math.random().toString(36).substring(2, 8);
  return `BRIDGE-AUTO-01-R${round}-${ts}-${rand}`;
}

async function createGpaiTask(marker) {
  const taskId = marker.toLowerCase().replace(/[^a-z0-9-]/g, '');
  const taskContent = {
    protocol: 'aiarchlab.peer-message/1',
    id: taskId,
    from: 'dsh-sd',
    to: 'gpai',
    subject: `BRIDGE-AUTO-01 Round task: ${marker}`,
    body: `BRIDGE-AUTO-01: 請掃描 AIArchLab/works 的 gpai inbox，處理帶標記 ${marker} 的任務，並將本次唯一標記寫回 repo (bridge/wake-tests/ 或 inbox/dsh-sd/)。\n\n唯一標記：${marker}`,
    marker: marker,
    created_at: new Date().toISOString()
  };
  const r = await ghApi('PUT', `/repos/${REPO}/contents/inbox/gpai/${taskId}.json`, {
    message: `BRIDGE-AUTO-01: create task ${marker}`,
    content: Buffer.from(JSON.stringify(taskContent, null, 2)).toString('base64')
  });
  log('Created gpai task: ' + taskId + ' (status ' + r.status + ')');
  return { taskId, marker };
}

async function pollForResponse(marker, timeoutMs = POLL_TIMEOUT_MS) {
  const startTime = Date.now();
  while (Date.now() - startTime < timeoutMs) {
    // Check inbox/dsh-sd for GPAI response with matching marker
    const r = await ghApi('GET', `/repos/${REPO}/contents/inbox/dsh-sd`);
    if (r.status === 200 && Array.isArray(r.data)) {
      for (const item of r.data) {
        if (!item.name.endsWith('.json')) continue;
        const fr = await ghApi('GET', `/repos/${REPO}/contents/inbox/dsh-sd/${item.name}`);
        if (fr.status === 200 && fr.data.content) {
          const content = Buffer.from(fr.data.content, 'base64').toString('utf8');
          if (content.includes(marker)) {
            log('Found GPAI response with marker ' + marker + ' in ' + item.name);
            return { file: item.name, content: JSON.parse(content) };
          }
        }
      }
    }
    // Check bridge/wake-tests for matching marker
    const r2 = await ghApi('GET', `/repos/${REPO}/contents/bridge/wake-tests`);
    if (r2.status === 200 && Array.isArray(r2.data)) {
      for (const item of r2.data) {
        if (item.name.includes(marker)) {
          const fr = await ghApi('GET', `/repos/${REPO}/contents/bridge/wake-tests/${item.name}`);
          if (fr.status === 200 && fr.data.content) {
            const content = Buffer.from(fr.data.content, 'base64').toString('utf8');
            log('Found wake-test result with marker ' + marker + ' in ' + item.name);
            return { file: item.name, content: JSON.parse(content) };
          }
        }
      }
    }
    log('Polling for response to ' + marker + '... (' + Math.round((Date.now()-startTime)/1000) + 's elapsed)');
    await new Promise(r => setTimeout(r, POLL_INTERVAL_MS));
  }
  throw new Error('Timeout waiting for GPAI response to ' + marker);
}

async function runRound(roundNum) {
  log('=== Starting Round ' + roundNum + ' ===');
  const marker = generateMarker(roundNum);
  log('Marker: ' + marker);

  // Step 1: Create task in gpai inbox
  const { taskId } = await createGpaiTask(marker);
  log('Task created: ' + taskId);

  // Step 2: Send message to GPAI via CDP
  const message = `BRIDGE-AUTO-01 Round ${roundNum}: 請掃描 AIArchLab/works 的 gpai inbox，處理帶標記 ${marker} 的任務，並將本次唯一標記寫回 repo。\n\n唯一標記：${marker}`;
  const cdpResult = await sendToGpai(message);
  log('CDP send result: ' + JSON.stringify(cdpResult));

  // Step 3: Poll for GPAI response
  const response = await pollForResponse(marker);
  log('GPAI response received: ' + JSON.stringify(response.content).substring(0, 300));

  // Step 4: Record round result
  const roundResult = {
    round: roundNum,
    marker: marker,
    taskId: taskId,
    cdpResult: cdpResult,
    response: response,
    completed_at: new Date().toISOString(),
    status: 'completed'
  };
  const resultFile = join(LOG_DIR, `round-${roundNum}-${marker}.json`);
  writeFileSync(resultFile, JSON.stringify(roundResult, null, 2));
  log('Round ' + roundNum + ' result saved to ' + resultFile);
  log('=== Round ' + roundNum + ' completed ===');
  return roundResult;
}

async function main() {
  const roundArg = process.argv.includes('--round') ? parseInt(process.argv[process.argv.indexOf('--round') + 1]) : null;
  if (roundArg) {
    // Single round mode
    await runRound(roundArg);
  } else {
    // Full two-round mode with 60s interval
    const r1 = await runRound(1);
    log('Waiting 60 seconds before round 2...');
    await new Promise(r => setTimeout(r, 60000));
    const r2 = await runRound(2);
    log('=== All rounds completed ===');
    log('Round 1 marker: ' + r1.marker);
    log('Round 2 marker: ' + r2.marker);
  }
}

main().catch(e => {
  log('FATAL ERROR: ' + e.message);
  log(e.stack);
  process.exit(1);
});
