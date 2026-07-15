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
        details.id = 'thinkingDetails';
        details.innerHTML = `
          <div class="thinking-details-header" onclick="toggleThinkingDetails(this)">
            <span class="arrow">&#x25B6;</span>
            <span class="status-text" id="thinkingStatusText">${escapeHtml(data.status || 'Thinking')}</span>
          </div>
          <div class="thinking-details-body" id="thinkingDetailsBody"></div>
        `;
        currentAssistantEl.appendChild(details);
      } else {
        const st = document.getElementById('thinkingStatusText');
        if (st) st.textContent = data.status || 'Thinking';
      }
      break;

    case 'thinking_status':
      updateThinkingBar(data.status || '');
      {
        const st = document.getElementById('thinkingStatusText');
        if (st) st.textContent = data.status || '';
      }
      break;

    case 'thinking_done':
      hideThinkingBar();
      {
        const st = document.getElementById('thinkingStatusText');
        if (st && st.textContent && st.textContent !== '') {
          st.textContent = 'Done';
        }
      }
      break;

    case 'tool_calls':
      if (!currentAssistantEl) {
        currentAssistantEl = createAssistantMessage();
      }
      addToolCallsToThinking(data.calls, data.phase || '');
      break;

    case 'tool_result':
      updateToolResult(data.id, data.name, data.success, data.content);
      break;

    case 'tool_results':
      if (data.results) {
        data.results.forEach(r => updateToolResult(r.id, r.name, true, r.content));
      }
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
      showToast(`Mode: ${mode}`);
      break;

    case 'model_switched':
      currentModel = data.model;
      document.getElementById('modelName').textContent = data.display || data.model;
      showToast(`Model: ${data.display || data.model}`);
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
  div.innerHTML = `<div class="message-header">Dekacode</div>`;
  messagesEl().appendChild(div);
  scrollToBottom();
  saveChatToStorage();
  return div;
}

function hideWelcome() {
  const w = welcomeEl();
  if (w) w.style.display = 'none';
}

// ─── Thinking Bar ─────────────────────────────────────────────────

let _thinkingStart = null;
let _tickerInterval = null;

function showThinkingBar(text) {
  const bar = document.getElementById('thinkingBar');
  document.getElementById('thinkingText').textContent = text;
  bar.style.display = 'flex';
  setSendButtonStop(true);
  _thinkingStart = Date.now();
  document.getElementById('thinkingElapsed').textContent = '0.0s';
  startTicker();
}

function updateThinkingBar(text) {
  document.getElementById('thinkingText').textContent = text;
}

function hideThinkingBar() {
  document.getElementById('thinkingBar').style.display = 'none';
  setSendButtonStop(false);
  _thinkingStart = null;
  stopTicker();
}

function startTicker() {
  stopTicker();
  _tickerInterval = setInterval(() => {
    if (_thinkingStart) {
      const elapsed = (Date.now() - _thinkingStart) / 1000;
      document.getElementById('thinkingElapsed').textContent = elapsed.toFixed(1) + 's';
    }
  }, 200);
}

function stopTicker() {
  if (_tickerInterval) {
    clearInterval(_tickerInterval);
    _tickerInterval = null;
  }
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

function stopGeneration() {
  sendJson({ type: 'stop' });
  setSendButtonStop(false);
  hideThinkingBar();
}

// ─── Thinking Details ─────────────────────────────────────────────

function toggleThinkingDetails(header) {
  const body = header.nextElementSibling;
  const arrow = header.querySelector('.arrow');
  body.classList.toggle('open');
  arrow.classList.toggle('open');
}

function addToolCallsToThinking(calls) {
  const detailsBody = document.getElementById('thinkingDetailsBody');
  if (!detailsBody) return;

  for (const call of calls) {
    const item = document.createElement('div');
    item.className = 'tool-result-item';
    item.dataset.callId = call.id;
    item.innerHTML = `
      <div class="item-line">
        <span class="status-icon">&#x23F3;</span>
        <span class="tool-name">[${escapeHtml(call.name)}]</span>
        <span class="item-args">${escapeHtml(formatArgs(call.args))}</span>
      </div>
    `;
    detailsBody.appendChild(item);
  }
  scrollToBottom();
}

function updateToolResult(id, name, success, content) {
  const item = document.querySelector(`.tool-result-item[data-call-id="${id}"]`);
  if (!item) return;
  const preview = (content || '').replace(/\n/g, ' ').slice(0, 200);
  const line = item.querySelector('.item-line');
  line.innerHTML = `
    <span class="status-icon">${success ? '\u2705' : '\u274C'}</span>
    <span class="tool-name">[${escapeHtml(name)}]</span>
    <span class="item-args">${escapeHtml(preview)}</span>
  `;
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
  input.style.height = Math.min(input.scrollHeight, 120) + 'px';
  handleCommandAutocomplete();
});

input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
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
  document.getElementById('thinkingBar').style.display = 'none';
  setSendButtonStop(false);
  hasSentMessage = false;
  showWelcome();
  sendJson({ type: 'message', content: '/clear' });
  localStorage.removeItem('dekacode_chat');
}

function newSession() {
  messagesEl().innerHTML = '';
  currentAssistantEl = null;
  document.getElementById('thinkingBar').style.display = 'none';
  setSendButtonStop(false);
  hasSentMessage = false;
  isProcessing = false;
  showWelcome();
  input.focus();
}

let sessionCounter = 0;
const SESSION_LIST_KEY = 'dekacode_sessions';

function saveSessionToList() {
  const preview = getChatPreview();
  if (!preview || preview === 'Empty conversation') return;
  let sessions = loadSessionList();
  const ts = Date.now();
  const existing = sessions.findIndex(s => s.id === 'current');
  if (existing >= 0) {
    sessions[existing] = { id: 'current', preview, ts, html: messagesEl().innerHTML };
  } else {
    sessions.push({ id: 'current', preview, ts, html: messagesEl().innerHTML });
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
      messagesEl().innerHTML = last.html;
      hasSentMessage = true;
      hideWelcome();
    } else {
      showWelcome();
    }
  } else {
    showWelcome();
  }
  updateSessionList();
}

// ─── Welcome / dekacode.png ────────────────────────────────────────

function showWelcome() {
  const w = welcomeEl();
  if (w) w.style.display = 'flex';
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
  messagesEl().innerHTML = s.html;
  hasSentMessage = true;
  hideWelcome();
  currentAssistantEl = null;
  document.getElementById('thinkingBar').style.display = 'none';
  setSendButtonStop(false);
  isProcessing = false;
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

function formatArgs(argsStr) {
  try {
    return JSON.stringify(JSON.parse(argsStr), null, 2);
  } catch {
    return argsStr;
  }
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
}

function toggleModelPanel() {
  const panel = document.getElementById('modelPanel');
  if (panel.style.display === 'block') {
    panel.style.display = 'none';
    return;
  }
  panel.innerHTML = availableModels.map(m =>
    `<div class="model-option ${m.id === currentModel ? 'active' : ''}" onclick="selectModel('${m.id}')">
      ${m.id === currentModel ? '<span class="model-check">&#x2713;</span>' : '<span class="model-check"></span>'}
      ${escapeHtml(m.label || m.id)}
    </div>`
  ).join('');
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

document.addEventListener('DOMContentLoaded', () => {
  // Cache-bust the logo
  const logo = document.getElementById('welcomeLogo');
  if (logo) logo.src = '/logo.png?_=' + Date.now();

  restoreChatFromStorage();
  connect();
  fetchModels();
  if (input) input.focus();
  document.getElementById('sendBtn').onclick = sendMessage;

  // Click thinking bar to toggle details
  const tbar = document.getElementById('thinkingBar');
  tbar.addEventListener('click', (e) => {
    if (e.target.closest('.stop-btn')) return;
    const details = document.getElementById('thinkingDetails');
    if (details) {
      const body = document.getElementById('thinkingDetailsBody');
      const arrow = details.querySelector('.arrow');
      if (body) {
        body.classList.toggle('open');
        if (arrow) arrow.classList.toggle('open');
      }
    }
  });
});
