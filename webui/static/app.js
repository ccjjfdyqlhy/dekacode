let ws = null;
let messageId = 0;
let currentAssistantEl = null;
let isProcessing = false;
let mode = 'agent';
let commands = [];
let cmdSelectedIdx = -1;
let hasSentMessage = false;

// ─── WebSocket ────────────────────────────────────────────────────

function connect() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${protocol}//${location.host}/ws`);

  ws.onopen = () => {
    showToast('Connected');
    fetchStatus();
    fetchCommands();
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    handleMessage(data);
  };

  ws.onclose = () => {
    showToast('Disconnected — reconnecting...');
    setTimeout(connect, 2000);
  };

  ws.onerror = () => ws.close();
}

function sendJson(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj));
  }
}

// ─── Message Handlers ─────────────────────────────────────────────

function handleMessage(data) {
  switch (data.type) {

    case 'thinking_start':
      showThinkingBar(data.status || 'Thinking...');
      if (!currentAssistantEl) {
        currentAssistantEl = createAssistantMessage();
        const details = document.createElement('div');
        details.className = 'thinking-details';
        details.innerHTML = `
          <div class="thinking-details-header" onclick="toggleThinkingDetails(this)">
            <span class="arrow">&#x25B6;</span>
            <span class="status-text">${escapeHtml(data.status || 'Thinking')}</span>
          </div>
          <div class="thinking-details-body"></div>
        `;
        currentAssistantEl.appendChild(details);
      } else {
        const st = currentAssistantEl.querySelector('.status-text');
        if (st) st.textContent = data.status || 'Thinking';
      }
      break;

    case 'thinking_status':
      updateThinkingBar(data.status || '');
      if (currentAssistantEl) {
        const st = currentAssistantEl.querySelector('.status-text');
        if (st) st.textContent = data.status || '';
        const lastItem = currentAssistantEl.querySelector('.tool-result-item:last-child .tool-detail');
        if (lastItem && data.status) {
          const parts = data.status.split(' ');
          if (parts.length > 1) lastItem.textContent = parts.slice(1).join(' ');
        }
      }
      break;

    case 'thinking_done':
      hideThinkingBar();
      isProcessing = false;
      if (currentAssistantEl) {
        const st = currentAssistantEl.querySelector('.status-text');
        if (st) {
          const count = currentAssistantEl.querySelectorAll('.tool-result-item').length;
          st.textContent = count > 0 ? `${count} tasks done` : 'Done';
        }
      }
      break;

    case 'tool_calls':
      addToolCallsToExec(data.calls);
      addToolCallsToThinking(data.calls);
      break;

    case 'tool_result':
      updateToolResult(data.id, data.name, data.success, data.content);
      if (currentAssistantEl) {
        const item = currentAssistantEl.querySelector(`.tool-result-item[data-call-id="${data.id}"]`);
        if (item) {
          const icon = item.querySelector('.status-icon');
          if (icon) icon.textContent = data.success ? '\u2705' : '\u274C';
        }
      }
      break;

    case 'tool_results':
      if (data.results) {
        data.results.forEach(r => {
          updateToolResult(r.id, r.name, true, r.content);
          if (currentAssistantEl) {
            const item = currentAssistantEl.querySelector(`.tool-result-item[data-call-id="${r.id}"]`);
            if (item) {
              const icon = item.querySelector('.status-icon');
              if (icon) icon.textContent = '\u2705';
            }
          }
        });
      }
      break;

    case 'summary':
      appendSummary(data);
      break;

    case 'text':
      appendAssistantText(data.content);
      break;

    case 'command_output':
      // Command responses: not from AI, reset processing immediately
      appendCommandOutput(data.content);
      break;

    case 'error':
      hideThinkingBar();
      appendError(data.content);
      break;

    case 'mode_changed':
      mode = data.mode;
      document.getElementById('modeBadge').textContent = mode;
      document.getElementById('modeBadge').className = 'mode-badge ' + mode;
      {
        const hint = document.getElementById('inputHint');
        hint.textContent = mode === 'oneshot'
          ? 'One-Shot mode \u2014 use @req, @sym, @grep, @ls, @tree to declare context'
          : '';
      }
      showToast(`Mode: ${mode}`);
      updateModelBtnLabel();
      break;

    case 'model_switched':
      currentModel = data.model;
      document.getElementById('modelName').textContent = data.display || data.model;
      showToast(`Model: ${data.display || data.model}`);
      updateModelBtnLabel();
      break;
  }
}

// ─── DOM ──────────────────────────────────────────────────────────

function $(sel) { return document.querySelector(sel); }

function messagesEl() { return document.getElementById('messages'); }

function welcomeEl() { return document.getElementById('welcome'); }

function scrollToBottom() {
  const el = messagesEl();
  el.scrollTop = el.scrollHeight;
}

function createAssistantMessage() {
  const div = document.createElement('div');
  div.className = 'message message-assistant';
  div.id = `msg-${++messageId}`;
  messagesEl().appendChild(div);
  scrollToBottom();
  saveChatToStorage();
  return div;
}

function hideWelcome() {
  const w = welcomeEl();
  if (w) w.style.display = "none";
}

// ─── Execution Panel (replaces thinking bar) ─────────────────────

function showThinkingBar(text) {
  const panel = document.getElementById('executionPanel');
  panel.style.display = 'block';
  document.getElementById('execStatus').textContent = text;
  document.getElementById('execElapsed').textContent = '0.0s';
  document.getElementById('execBody').innerHTML = '';
  setSendButtonStop(true);
  _execStart = Date.now();
  startExecTicker();
}

function updateThinkingBar(text) {
  document.getElementById('execStatus').textContent = text;
}

function hideThinkingBar() {
  document.getElementById('executionPanel').style.display = 'none';
  setSendButtonStop(false);
  stopExecTicker();
}

function stopGeneration() {
  sendJson({ type: 'stop' });
  hideThinkingBar();
}

function setSendButtonStop(isStop) {
  const btn = document.getElementById('sendBtn');
  if (isStop) {
    btn.classList.add('stop');
    btn.innerHTML = '&#x25A0;';
    btn.onclick = stopGeneration;
  } else {
    btn.classList.remove('stop');
    btn.innerHTML = '&#x27A4;';
    btn.onclick = sendMessage;
  }
}

// ─── Thinking Details (in-message record) ────────────────────────

function toggleThinkingDetails(header) {
  const body = header.nextElementSibling;
  const arrow = header.querySelector('.arrow');
  body.classList.toggle('open');
  arrow.classList.toggle('open');
}

function addToolCallsToThinking(calls) {
  let body;
  if (currentAssistantEl) {
    body = currentAssistantEl.querySelector('.thinking-details-body');
  }
  if (!body) {
    if (!currentAssistantEl) currentAssistantEl = createAssistantMessage();
    const details = document.createElement('div');
    details.className = 'thinking-details';
    details.innerHTML = `
      <div class="thinking-details-header" onclick="toggleThinkingDetails(this)">
        <span class="arrow">&#x25B6;</span>
        <span class="status-text">Thinking</span>
      </div>
      <div class="thinking-details-body"></div>
    `;
    currentAssistantEl.appendChild(details);
    body = currentAssistantEl.querySelector('.thinking-details-body');
    if (!body) return;
  }
  for (const call of calls) {
    let detail = '';
    try {
      const args = JSON.parse(call.args);
      if (call.name === 'read_file') {
        const p = args.filePath || '';
        const o = args.offset;
        const l = args.limit;
        detail = o && l ? `${p}:${o}-${l}` : p;
      } else if (call.name === 'write_file') {
        detail = args.filePath || '';
      } else if (call.name === 'edit_file') {
        detail = args.filePath || '';
      } else if (call.name === 'glob') {
        detail = args.pattern || '';
      } else if (call.name === 'grep' || call.name === 'grep_context') {
        detail = `/${args.pattern || ''}/`;
      } else if (call.name === 'bash') {
        const cmd = (args.command || '').split('\n')[0];
        detail = cmd ? `$ ${cmd.slice(0, 60)}` : '';
      } else if (call.name === 'web_fetch') {
        detail = args.url || '';
      } else if (call.name === 'symbol_search') {
        detail = args.query || '';
      } else if (call.name === 'callers' || call.name === 'read_symbol') {
        detail = args.symbol || '';
      } else if (call.name === 'list_dir') {
        detail = args.path || '';
      } else if (call.name === 'py_check') {
        detail = args.file_path || '';
      } else if (call.name === 'read_files') {
        const ps = args.paths || [];
        detail = `${ps.length} files`;
      }
    } catch (e) {}
    const item = document.createElement('div');
    item.className = 'tool-result-item';
    item.dataset.callId = call.id;
    item.innerHTML = `
      <span class="status-icon">&#x23F3;</span>
      <span class="tool-name">${escapeHtml(call.name)}</span>
      ${detail ? `<span class="tool-detail">${escapeHtml(detail)}</span>` : ''}
    `;
    body.appendChild(item);
  }
}

// ─── Execution Panel (live above input) ───────────────────────────

let _execStart = null;
let _execTicker = null;

function toggleExecutionPanel(header) {
  const body = header.nextElementSibling;
  const arrow = header.querySelector('.arrow');
  body.classList.toggle('open');
  arrow.classList.toggle('open');
}

function addToolCallsToExec(calls) {
  const body = document.getElementById('execBody');
  if (!body) return;
  for (const call of calls) {
    const item = document.createElement('div');
    item.className = 'exec-item';
    item.dataset.callId = call.id;
    item.innerHTML = `
      <span class="exec-icon">&#x23F3;</span>
      <span class="exec-name">${escapeHtml(call.name)}</span>
    `;
    body.appendChild(item);
  }
}

function updateToolResult(id, name, success) {
  const item = document.querySelector(`.exec-item[data-call-id="${id}"]`);
  if (!item) return;
  item.querySelector('.exec-icon').textContent = success ? '\u2705' : '\u274C';
}

function startExecTicker() {
  stopExecTicker();
  _execTicker = setInterval(() => {
    if (_execStart) {
      const elapsed = (Date.now() - _execStart) / 1000;
      document.getElementById('execElapsed').textContent = elapsed.toFixed(1) + 's';
    }
  }, 200);
}

function stopExecTicker() {
  if (_execTicker) {
    clearInterval(_execTicker);
    _execTicker = null;
  }
}

// ─── Messages ─────────────────────────────────────────────────────

function appendUserMessage(text) {
  hideWelcome();
  const div = document.createElement('div');
  div.className = 'message message-user';
  div.id = `msg-${++messageId}`;
  div.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
  messagesEl().appendChild(div);
  scrollToBottom();
  saveChatToStorage();
}

function appendAssistantText(text) {
  hideWelcome();
  if (!currentAssistantEl) {
    currentAssistantEl = createAssistantMessage();
  }
  let contentEl = currentAssistantEl.querySelector('.message-content');
  if (!contentEl) {
    contentEl = document.createElement('div');
    contentEl.className = 'message-content';
    currentAssistantEl.appendChild(contentEl);
  }
  contentEl.innerHTML = renderMarkdown(text);
  scrollToBottom();
  hasSentMessage = true;
  saveSessionToList();
}

function appendCommandOutput(text) {
  hideWelcome();
  currentAssistantEl = null;
  const div = document.createElement('div');
  div.className = 'message message-assistant';
  div.id = `msg-${++messageId}`;
  div.innerHTML = `<div class="message-header" style="color:var(--text-dim)">System</div>
    <div class="message-content">${escapeHtml(text)}</div>`;
  messagesEl().appendChild(div);
  scrollToBottom();
  isProcessing = false;
}

function appendSummary(data) {
  if (!currentAssistantEl) {
    currentAssistantEl = createAssistantMessage();
  }
  let summaryEl = currentAssistantEl.querySelector('.summary-bar');
  if (!summaryEl) {
    summaryEl = document.createElement('div');
    summaryEl.className = 'summary-bar';
    currentAssistantEl.appendChild(summaryEl);
  }
  const fmt = (n) => {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
    return String(n);
  };
  let balanceHtml = '';
  const bal = window._balance;
  if (bal && bal.balanceUsd !== undefined) {
    balanceHtml = `<span title="Balance">$${bal.balanceUsd.toFixed(2)}</span>`;
  }
  summaryEl.innerHTML = `
    <span title="Input tokens">↑ ${fmt(data.input_tokens)} in</span>
    <span title="Output tokens">↓ ${fmt(data.output_tokens)} out</span>
    <span title="Cache hit">cache ${fmt(data.cache_hit)}/${data.cache_pct}%</span>
    <span title="Cost">¥${data.cost}</span>
    <span title="Context usage">ctx ${data.ctx_pct}%</span>
    <span title="Output usage">out ${data.out_pct}%</span>
    <span title="Elapsed">${data.elapsed}s</span>
    ${balanceHtml}
  `;
  // Fetch balance in background
  fetch('/api/balance').then(r => r.json()).then(b => { window._balance = b; }).catch(() => {});
}

function appendError(text) {
  hideWelcome();
  const div = document.createElement('div');
  div.className = 'message message-assistant';
  div.innerHTML = `<div class="message-header" style="color:var(--red)">Error</div>
    <div class="message-content" style="color:var(--red)">${escapeHtml(text)}</div>`;
  messagesEl().appendChild(div);
  scrollToBottom();
  saveChatToStorage();
}

// ─── Input ────────────────────────────────────────────────────────

const input = document.getElementById('input');

input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 240) + 'px';
  handleCommandAutocomplete();
});

input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.ctrlKey && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
  if (e.key === 'Escape') {
    hideCmdPanel();
  }
  if (e.key === 'Tab') {
    const panel = document.getElementById('cmdPanel');
    if (panel.style.display !== 'none' && cmdSelectedIdx >= 0) {
      e.preventDefault();
      selectCommand(cmdSelectedIdx);
    }
  }
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    const panel = document.getElementById('cmdPanel');
    if (panel.style.display !== 'none') {
      e.preventDefault();
      const items = panel.querySelectorAll('.cmd-item');
      if (e.key === 'ArrowDown') {
        cmdSelectedIdx = Math.min(cmdSelectedIdx + 1, items.length - 1);
      } else {
        cmdSelectedIdx = Math.max(cmdSelectedIdx - 1, 0);
      }
      items.forEach((el, i) => el.classList.toggle('selected', i === cmdSelectedIdx));
    }
  }
});

function sendMessage() {
  if (isProcessing) return;
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  input.style.height = 'auto';
  hideCmdPanel();

  appendUserMessage(text);
  currentAssistantEl = null;
  hasSentMessage = true;
  isProcessing = true;
  sendJson({ type: 'message', content: text });
}

// ─── Command Autocomplete ─────────────────────────────────────────

function handleCommandAutocomplete() {
  const text = input.value;
  const cursorPos = input.selectionStart;
  const beforeCursor = text.slice(0, cursorPos);
  const lineStart = beforeCursor.lastIndexOf('\n') + 1;
  const fromLineStart = beforeCursor.slice(lineStart);

  if (fromLineStart === '/') {
    showAllCommands();
    cmdSelectedIdx = 0;
  } else if (fromLineStart.startsWith('/')) {
    const partial = fromLineStart.slice(1).toLowerCase();
    showFilteredCommands(partial);
    cmdSelectedIdx = 0;
  } else {
    hideCmdPanel();
  }
}

function showAllCommands() {
  const panel = document.getElementById('cmdPanel');
  panel.innerHTML = commands.map((c, i) =>
    `<div class="cmd-item ${i === 0 ? 'selected' : ''}" onclick="selectCommandByCmd('${c.cmd}')">
      <span class="cmd-key">${escapeHtml(c.cmd)}</span>
      <span class="cmd-desc">${escapeHtml(c.desc)}</span>
    </div>`
  ).join('');
  panel.style.display = 'block';
}

function showFilteredCommands(partial) {
  const filtered = commands.filter(c =>
    c.cmd.slice(1).toLowerCase().includes(partial) ||
    c.desc.toLowerCase().includes(partial)
  );
  const panel = document.getElementById('cmdPanel');
  if (filtered.length === 0) {
    panel.style.display = 'none';
    return;
  }
  panel.innerHTML = filtered.map((c, i) =>
    `<div class="cmd-item ${i === 0 ? 'selected' : ''}" onclick="selectCommandByCmd('${c.cmd}')">
      <span class="cmd-key">${escapeHtml(c.cmd)}</span>
      <span class="cmd-desc">${escapeHtml(c.desc)}</span>
    </div>`
  ).join('');
  panel.style.display = 'block';
}

function selectCommand(idx) {
  const panel = document.getElementById('cmdPanel');
  const items = panel.querySelectorAll('.cmd-item');
  if (items[idx]) {
    const cmd = items[idx].querySelector('.cmd-key').textContent;
    insertCommand(cmd);
  }
}

function selectCommandByCmd(cmd) {
  insertCommand(cmd);
}

function insertCommand(cmd) {
  const text = input.value;
  const cursorPos = input.selectionStart;
  const beforeCursor = text.slice(0, cursorPos);
  const lineStart = beforeCursor.lastIndexOf('\n') + 1;
  const beforeLine = text.slice(0, lineStart);
  const afterCursor = text.slice(cursorPos);

  input.value = beforeLine + cmd + ' ' + afterCursor;
  const newPos = beforeLine.length + cmd.length + 1;
  input.setSelectionRange(newPos, newPos);
  hideCmdPanel();
  input.focus();
}

function hideCmdPanel() {
  document.getElementById('cmdPanel').style.display = 'none';
  cmdSelectedIdx = -1;
}

// ─── Commands ─────────────────────────────────────────────────────

async function fetchCommands() {
  try {
    const resp = await fetch('/api/commands');
    commands = await resp.json();
  } catch (e) {
    commands = [
      { cmd: '/mode', desc: 'Toggle agent/oneshot mode' },
      { cmd: '/help', desc: 'Show available commands' },
      { cmd: '/clear', desc: 'Clear conversation' },
      { cmd: '/stats', desc: 'Show context stats' },
      { cmd: '/cost', desc: 'Show session token cost' },
    ];
  }
}

function toggleMode() {
  const newMode = mode === 'agent' ? 'oneshot' : 'agent';
  sendJson({ type: 'mode', mode: newMode });
  const hint = document.getElementById('inputHint');
  hint.textContent = newMode === 'oneshot'
    ? 'One-Shot mode \u2014 use @req, @sym, @grep, @ls, @tree to declare context'
    : '';
}

function clearChat() {
  messagesEl().innerHTML = '';
  currentAssistantEl = null;
  document.getElementById('executionPanel').style.display = 'none';
  setSendButtonStop(false);
  hasSentMessage = false;
  showWelcome();
  sendJson({ type: 'message', content: '/clear' });
}

function newSession() {
  saveCurrentBeforeNew();
  sessionId = _genId();
  messagesEl().innerHTML = '';
  currentAssistantEl = null;
  document.getElementById('executionPanel').style.display = 'none';
  setSendButtonStop(false);
  hasSentMessage = false;
  isProcessing = false;
  const w = document.getElementById('welcome');
  if (w) w.style.display = 'flex';
  input.focus();
  updateSessionList();
}

let sessionId = 'sess_' + Date.now();
const SESSION_LIST_KEY = 'dekacode_sessions';

function _genId() { return 'sess_' + Date.now() + '_' + Math.random().toString(36).slice(2, 6); }

function saveSessionToList() {
  const preview = getChatPreview();
  if (!preview || preview === 'Empty conversation') return;
  let sessions = loadSessionList();
  const ts = Date.now();
  const existing = sessions.findIndex(s => s.id === sessionId);
  if (existing >= 0) {
    sessions[existing] = { id: sessionId, preview, ts, html: messagesEl().innerHTML };
  } else {
    sessions.push({ id: sessionId, preview, ts, html: messagesEl().innerHTML });
  }
  sessions = sessions.slice(-20);
  try {
    localStorage.setItem(SESSION_LIST_KEY, JSON.stringify(sessions));
  } catch (e) { /* ignore */ }
  updateSessionList();
}

function loadSessionList() {
  try {
    const raw = localStorage.getItem(SESSION_LIST_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

function saveCurrentBeforeNew() {
  const html = messagesEl().innerHTML;
  if (!html.trim()) return;
  let sessions = loadSessionList();
  const existing = sessions.findIndex(s => s.id === sessionId);
  if (existing >= 0) {
    sessions[existing].html = html;
    sessions[existing].ts = Date.now();
  } else {
    sessions.push({ id: sessionId, preview: getChatPreview() || '(chat)', ts: Date.now(), html });
  }
  sessions = sessions.slice(-20);
  try { localStorage.setItem(SESSION_LIST_KEY, JSON.stringify(sessions)); } catch (e) {}
}

function optionsMenu() {
  const menu = document.getElementById('optionsMenu');
  menu.classList.toggle('open');
}

document.addEventListener('click', (e) => {
  const menu = document.getElementById('optionsMenu');
  const btn = document.querySelector('.action-btn');
  if (menu && menu.classList.contains('open') && !menu.contains(e.target) && !btn.contains(e.target)) {
    menu.classList.remove('open');
  }
});

// ─── localStorage Persistence ─────────────────────────────────────

const STORAGE_KEY = 'dekacode_chat';

function saveChatToStorage() {
  const html = messagesEl().innerHTML;
  try {
    localStorage.setItem(STORAGE_KEY, html);
  } catch (e) { /* quota exceeded */ }
}

function restoreChatFromStorage() {
  const sessions = loadSessionList();
  if (sessions.length > 0) {
    const last = sessions[sessions.length - 1];
    if (last && last.html) {
      sessionId = last.id;
      messagesEl().innerHTML = last.html;
      document.querySelectorAll('.thinking-details').forEach(d => {
        const st = d.querySelector('.status-text');
        if (st) {
          const count = d.querySelectorAll('.tool-result-item').length;
          st.textContent = count > 0 ? `${count} tasks done` : 'Done';
        }
      });
      hasSentMessage = true;
      hideWelcome();
    } else {
      showWelcome();
    }
  } else {
    showWelcome();
  }
  updateSessionList();
  scrollToBottom();
}

// ─── Welcome / dekacode.png ────────────────────────────────────────

function showWelcome() {
  const w = welcomeEl();
  if (w) w.style.display = "";
}

// ─── Session List ─────────────────────────────────────────────────

function updateSessionList() {
  const list = document.getElementById('sessionList');
  if (!list) return;
  const sessions = loadSessionList();
  if (sessions.length === 0) {
    list.innerHTML = '<div class="session-empty">No sessions yet</div>';
    return;
  }
  list.innerHTML = sessions.slice().reverse().map((e, i) =>
    `<div class="session-item ${i === 0 ? 'active' : ''}" onclick="restoreSession(${sessions.length - 1 - i})">
      <div class="session-preview">${escapeHtml(e.preview)}</div>
      <div class="session-time">${formatTime(e.ts)}</div>
    </div>`
  ).join('');
}

function restoreSession(idx) {
  const sessions = loadSessionList();
  const s = sessions[idx];
  if (!s || !s.html) return;
  saveCurrentBeforeNew();
  sessionId = s.id;
  messagesEl().innerHTML = s.html;
  // Mark all thinking-details status as Done
  document.querySelectorAll('.thinking-details').forEach(d => {
    const st = d.querySelector('.status-text');
    if (st) {
      const count = d.querySelectorAll('.tool-result-item').length;
      st.textContent = count > 0 ? `${count} tasks done` : 'Done';
    }
  });
  hasSentMessage = true;
  hideWelcome();
  currentAssistantEl = null;
  document.getElementById('executionPanel').style.display = 'none';
  setSendButtonStop(false);
  isProcessing = false;
  updateSessionList();
}

function getChatPreview() {
  const msgs = messagesEl().querySelectorAll('.message-user .bubble');
  if (msgs.length === 0) return '';
  let texts = [];
  for (const m of msgs) {
    const t = m.textContent.trim();
    if (t && !t.startsWith('/')) {
      texts.push(t);
    }
  }
  if (texts.length === 0) return '';
  return texts[texts.length - 1].slice(0, 60);
}

function formatTime(ts) {
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// ─── Markdown ─────────────────────────────────────────────────────

function renderMarkdown(text) {
  if (!text) return '';
  let html = escapeHtml(text);
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (m, lang, code) => `<pre><code>${escapeHtml(code)}</code></pre>`);
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
  html = html.replace(/^(\|.+\|)\n(\|[-:| ]+\|)\n((?:\|.+\|\n?)*)/gm, (_, head, sep, body) => {
    const headers = head.slice(1, -1).split('|').map(c => `<th>${c.trim()}</th>`).join('');
    const rows = body.trim().split('\n').filter(Boolean).map(line => {
      const cells = line.slice(1, -1).split('|').map(c => `<td>${c.trim()}</td>`).join('');
      return `<tr>${cells}</tr>`;
    }).join('');
    return `<table><thead><tr>${headers}</tr></thead><tbody>${rows}</tbody></table>`;
  });
  html = html.replace(/^[-*_]{3,}\s*$/gm, '<hr>');
  html = html.replace(/\n\n/g, '</p><p>');
  html = html.replace(/\n/g, '<br>');
  return '<p>' + html + '</p>';
}

// ─── Utilities ────────────────────────────────────────────────────

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function showToast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(el._timeout);
  el._timeout = setTimeout(() => el.classList.remove('show'), 2500);
}

// ─── Status ───────────────────────────────────────────────────────

let currentModel = 'flash';
let availableModels = [];

async function fetchStatus() {
  try {
    const resp = await fetch('/api/status');
    const data = await resp.json();
    document.getElementById('modelName').textContent = data.model || '\u2014';
    document.getElementById('symbolCount').textContent = data.symbols || '\u2014';
    const projEl = document.getElementById('welcomeProject');
    if (projEl && data.project) {
      projEl.textContent = data.project;
    }
  } catch (e) { /* ignore */ }
}

async function fetchModels() {
  try {
    const resp = await fetch('/api/models');
    availableModels = await resp.json();
    if (availableModels.length > 0) {
      currentModel = availableModels.find(m => m.active)?.id || availableModels[0].id;
    }
  } catch (e) {
    availableModels = [
      { id: 'flash', label: 'Flash', active: true },
      { id: 'pro', label: 'Pro', active: false },
    ];
  }
  updateModelBtnLabel();
}

function updateModelBtnLabel() {
  const label = document.getElementById('modelBtnLabel');
  if (!label) return;
  const modeName = mode === 'agent' ? 'Agent' : 'OneShot';
  const modelName = (availableModels.find(m => m.id === currentModel)?.label || currentModel);
  label.textContent = modeName + ' ' + modelName;
}

function toggleModelPanel() {
  const panel = document.getElementById('modelPanel');
  if (panel.style.display === 'block') {
    panel.style.display = 'none';
    return;
  }

  const modeLabel = mode === 'agent' ? 'Agent' : 'OneShot';

  let modeHtml = `
    <div class="mp-section mp-mode-section">
      <div class="mp-mode-label">${modeLabel}</div>
      <div class="mp-slider">
        <div class="mp-slider-option ${mode === 'agent' ? 'active' : ''}" onclick="setMode('agent')">Agent</div>
        <div class="mp-slider-option ${mode === 'oneshot' ? 'active' : ''}" onclick="setMode('oneshot')">OneShot</div>
        <div class="mp-slider-option locked">anaii</div>
      </div>
    </div>`;

  let modelHtml = `<div class="mp-section">`;
  for (const m of availableModels) {
    const active = m.id === currentModel ? 'active' : '';
    const label = m.label || m.id;
    modelHtml += `
      <div class="model-option ${active}" onclick="selectModel('${m.id}')">
        <div class="mo-main">${active ? '<span class="model-check">&#x2713;</span> ' : ''}${escapeHtml(label)}</div>
        <div class="mo-sub">${escapeHtml(m.model || '')}</div>
      </div>`;
  }
  modelHtml += `</div>`;

  panel.innerHTML = modeHtml + modelHtml;
  panel.style.display = 'block';
}

function selectModel(id) {
  if (id === currentModel) {
    document.getElementById('modelPanel').style.display = 'none';
    return;
  }
  currentModel = id;
  sendJson({ type: 'switch_model', model: id });
  document.getElementById('modelPanel').style.display = 'none';
  updateModelBtnLabel();
}

function setMode(newMode) {
  if (newMode === mode) {
    document.getElementById('modelPanel').style.display = 'none';
    return;
  }
  mode = newMode;
  sendJson({ type: 'mode', mode: newMode });
  document.getElementById('modeBadge').textContent = newMode;
  document.getElementById('modeBadge').className = 'mode-badge ' + newMode;
  const hint = document.getElementById('inputHint');
  hint.textContent = newMode === 'oneshot'
    ? 'One-Shot mode \u2014 use @req, @sym, @grep, @ls, @tree to declare context'
    : '';
  document.getElementById('modelPanel').style.display = 'none';
  updateModelBtnLabel();
}

// Close model panel on outside click
document.addEventListener('click', (e) => {
  const panel = document.getElementById('modelPanel');
  const btn = document.getElementById('modelBtn');
  if (panel && panel.style.display === 'block' && !panel.contains(e.target) && !btn.contains(e.target)) {
    panel.style.display = 'none';
  }
});

// ─── Init ─────────────────────────────────────────────────────────

function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  sidebar.classList.toggle('collapsed');
  const btn = document.getElementById('sidebarToggle');
  if (sidebar.classList.contains('collapsed')) {
    btn.style.left = '10px';
  } else {
    btn.style.left = '226px';
  }
}

const WELCOME_PHRASES = [
  "How can I help you?",
  "What are we building today?",
  "Ready to code — what's the plan?",
  "What would you like me to work on?",
  "Fire away — what do you need?",
  "What's on your mind?",
  "Let's build something great.",
  "I'm listening — what's the task?",
  "What should we tackle next?",
  "Tell me what you need done.",
  "All ears — where do we start?",
  "What's the mission?",
  "Ready when you are — what's first?",
  "What can I help you craft?",
];

document.addEventListener('DOMContentLoaded', () => {
  // Set random welcome phrase
  const wt = document.querySelector('.welcome-text');
  if (wt) wt.textContent = WELCOME_PHRASES[Math.floor(Math.random() * WELCOME_PHRASES.length)];

  // Cache-bust the logo
  const logo = document.getElementById('welcomeLogo');
  if (logo) logo.src = '/logo.png?_=' + Date.now();

  restoreChatFromStorage();
  connect();
  fetchModels();
  if (input) input.focus();
  document.getElementById('sendBtn').onclick = sendMessage;

});
