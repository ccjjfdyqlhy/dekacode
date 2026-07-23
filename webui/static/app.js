let ws = null;
let messageId = 0;
let currentAssistantEl = null;
let isProcessing = false;
let mode = 'agent';
let commands = [];
let cmdSelectedIdx = -1;
let hasSentMessage = false;
let thinkingCollapsed = true;
let _thinkingTimer = null;
let isTempChat = false;
let _prevSessionState = null;
let _optionsOpen = false;

// ─── WebSocket ────────────────────────────────────────────────────

function connect() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${protocol}//${location.host}/ws`);

  ws.onopen = () => {
    showToast('Connected');
    fetchStatus();
    fetchCommands();
    fetchOptions();
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
      showThinkingBar();
      if (!currentAssistantEl) {
        currentAssistantEl = createAssistantMessage();
      }
      ensureThinkingEl(thinkingCollapsed);
      break;

    case 'thinking_text':
      if (currentAssistantEl) {
        updateThinkingBanner(data.content);
      }
      break;

    case 'thinking_status':
      updateThinkingBar(data.status || '');
      if (currentAssistantEl) {
        const st = currentAssistantEl.querySelector('.thinking-banner-text');
        if (st && data.status) st.textContent = data.status;
      }
      break;

    case 'thinking_done':
      hideThinkingBar();
      isProcessing = false;
      if (currentAssistantEl) {
        const st = currentAssistantEl.querySelector('.thinking-banner-text');
        if (st && st.textContent) {
          const label = st.textContent.trim();
          const past = {
            'Thinking': 'Thought', 'Bashing': 'Bashed', 'Reading': 'Read',
            'Writing': 'Wrote', 'Editing': 'Edited', 'Globbing': 'Globbed',
            'Grepping': 'Grepped', 'Fetching': 'Fetched', 'Searching': 'Searched',
            'Tracing': 'Traced', 'Checking': 'Checked', 'Batching': 'Batched',
            'Listing': 'Listed', 'Diffing': 'Diffed', 'Analyzing': 'Analyzed',
            'Resolving': 'Resolved', 'Streaming': 'Streamed',
            'Preparing command': 'Command prepared', 'Preparing read': 'Read prepared',
            'Preparing write': 'Write prepared', 'Preparing edit': 'Edit prepared',
            'Preparing search': 'Search prepared', 'Preparing list': 'List prepared',
            'Preparing diff': 'Diff prepared', 'Preparing analysis': 'Analysis prepared',
            'Preparing fetch': 'Fetch prepared', 'Preparing trace': 'Trace prepared',
            'Preparing check': 'Check prepared',
          };
          st.textContent = past[label] || past[label.split(':')[0].trim()] || label;
        }
      }
      break;

    case 'tool_calls':
      addToolCallsToExec(data.calls);
      if (currentAssistantEl) {
        for (const call of data.calls) {
          addThinkingToolItem(call);
        }
      }
      break;

    case 'tool_result':
      updateToolResult(data.id, data.name, data.success, data.content);
      if (currentAssistantEl) {
        const item = currentAssistantEl.querySelector(`.thinking-tool-item[data-call-id="${data.id}"]`);
        if (item) {
          item.style.color = data.success ? 'var(--green)' : 'var(--red)';
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

    case 'text_delta':
      appendAssistantTextDelta(data.content);
      break;

    case 'reasoning_delta':
      appendReasoningDelta(data.content);
      break;

    case 'progress':
      updateProgressBar(data.elapsed, data.estimated);
      break;

    case 'todo':
      showTodoList(data.items, data.done);
      break;

    case 'sub_task_start':
      showSubTasks(data.tasks);
      break;

    case 'sub_task_result':
      updateSubTask(data.title, data.success, data.elapsed, data.tools);
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
  checkScrollPosition();
}

function checkScrollPosition() {
  const el = messagesEl();
  const inputArea = document.getElementById('inputArea');
  const hint = document.getElementById('scrollHint');
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  if (atBottom) {
    inputArea.classList.remove('scrolled-up');
    if (hint) hint.style.display = 'none';
  } else {
    inputArea.classList.add('scrolled-up');
    if (hint) hint.style.display = 'block';
  }
}

function scrollToTop() {
  messagesEl().scrollTop = 0;
  checkScrollPosition();
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

function showThinkingBar() {
  const panel = document.getElementById('executionPanel');
  panel.style.display = 'block';
  const bar = panel.querySelector('.ep-progress-fill');
  if (bar) bar.style.width = '0%';
  document.getElementById('execStatus').textContent = 'Thinking...';
  document.getElementById('execElapsed').textContent = '';
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

// ─── Thinking Banner (in-message) ──────────────────────────────────

function ensureThinkingEl(collapsed) {
  if (!currentAssistantEl) return;
  let details = currentAssistantEl.querySelector('.thinking-details');
  if (!details) {
    details = document.createElement('div');
    details.className = 'thinking-details';
    const header = document.createElement('div');
    header.className = 'thinking-details-header';
    header.onclick = function() { toggleThinkingDetails(header); };
    header.innerHTML = `
      <span class="arrow">&#x25B6;</span>
      <span class="thinking-banner-text"></span>
    `;
    const body = document.createElement('div');
    body.className = 'thinking-details-body';
    details.appendChild(header);
    details.appendChild(body);
    currentAssistantEl.appendChild(details);
    if (collapsed) {
      body.style.display = 'none';
      header.classList.add('collapsed');
    } else {
      header.querySelector('.arrow').textContent = '\u25BC';
      body.style.display = 'block';
      header.classList.remove('collapsed');
    }
  }
}

function updateThinkingBanner(text) {
  if (!currentAssistantEl) return;
  ensureThinkingEl(thinkingCollapsed);
  const header = currentAssistantEl.querySelector('.thinking-details-header');
  const banner = currentAssistantEl.querySelector('.thinking-banner-text');
  if (!header || !banner) return;
  if (!header._texts) header._texts = [];
  header._texts.push(text);
  if (header._texts.length > 6) header._texts.shift();
  const clean = text.slice(0, 120).replace(/\n/g, ' ');
  if (!clean) return;
  banner.style.opacity = '1';
  banner.style.transform = 'translateY(0)';
  banner.textContent = clean;
  if (_thinkingTimer) clearTimeout(_thinkingTimer);
  _thinkingTimer = setTimeout(() => {
    banner.style.opacity = '0.6';
  }, 800);
}

function addThinkingToolItem(call) {
  if (!currentAssistantEl) return;
  ensureThinkingEl(thinkingCollapsed);
  const body = currentAssistantEl.querySelector('.thinking-details-body');
  if (!body) return;
  let detail = '';
  try {
    const args = JSON.parse(call.args);
    if (call.name === 'read_file') {
      const p = args.filePath || '';
      const o = args.offset; const l = args.limit;
      detail = o && l ? `${p}:${o}-${l}` : p;
    } else if (call.name === 'write_file' || call.name === 'edit_file') {
      detail = args.filePath || '';
    } else if (call.name === 'bash') {
      detail = (args.command || '').split('\n')[0].slice(0, 60);
    } else if (call.name === 'glob') {
      detail = args.pattern || '';
    } else if (call.name === 'grep' || call.name === 'grep_context') {
      detail = '/' + (args.pattern || '') + '/';
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
    }
  } catch (e) {}
  const item = document.createElement('div');
  item.className = 'thinking-tool-item';
  item.setAttribute('data-call-id', call.id);
  item.textContent = call.name + (detail ? ': ' + detail : '');
  item.style.color = 'var(--text-dim)';
  body.appendChild(item);
  const banner = currentAssistantEl.querySelector('.thinking-banner-text');
  if (banner) banner.textContent = toolStatusLabel(call.name) + (detail ? ': ' + detail : '');
}

function toolStatusLabel(name) {
  const m = {
    bash:'Running', read_file:'Reading', write_file:'Writing', edit_file:'Editing',
    glob:'Globbing', grep:'Grepping', grep_context:'Grepping', list_dir:'Listing',
    diff_file:'Diffing', ast_summary:'Analyzing', web_fetch:'Fetching',
    symbol_search:'Searching', callers:'Tracing', read_symbol:'Reading',
    py_check:'Checking', github:'GitHubbing', todowrite:'Updating todo'
  };
  return m[name] || 'Working';
}

function toggleThinkingDetails(header) {
  const body = header.nextElementSibling;
  const arrow = header.querySelector('.arrow');
  if (body.style.display === 'none' || !body.style.display) {
    body.style.display = 'block';
    arrow.textContent = '\u25BC';
    header.classList.remove('collapsed');
    let reasonEl = body.querySelector('.thinking-reason');
    if (!reasonEl) {
      reasonEl = document.createElement('div');
      reasonEl.className = 'thinking-reason';
      body.insertBefore(reasonEl, body.firstChild);
    }
    if (header._texts) reasonEl.textContent = header._texts.join('\n');
  } else {
    body.style.display = 'none';
    arrow.textContent = '\u25B6';
    header.classList.add('collapsed');
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

function appendAssistantTextDelta(text) {
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
  let rawEl = currentAssistantEl.querySelector('.message-raw');
  if (!rawEl) {
    rawEl = document.createElement('div');
    rawEl.className = 'message-raw';
    rawEl.style.display = 'none';
    currentAssistantEl.appendChild(rawEl);
  }
  rawEl.textContent += text;
  contentEl.innerHTML = renderMarkdown(rawEl.textContent);
  scrollToBottom();
}

function appendReasoningDelta(text) {
  hideWelcome();
  if (!currentAssistantEl) {
    currentAssistantEl = createAssistantMessage();
  }
  let thinkingEl = currentAssistantEl.querySelector('.thinking-details');
  if (!thinkingEl) {
    thinkingEl = document.createElement('div');
    thinkingEl.className = 'thinking-details';
    const header = document.createElement('div');
    header.className = 'thinking-details-header';
    header.onclick = function() { toggleThinkingDetails(header); };
    header.innerHTML = '<span class="arrow">&#x25B6;</span><span class="status-text">Thought</span>';
    const body = document.createElement('div');
    body.className = 'thinking-details-body';
    body.style.display = 'none';
    thinkingEl.appendChild(header);
    thinkingEl.appendChild(body);
    currentAssistantEl.appendChild(thinkingEl);
  }
  const body = thinkingEl.querySelector('.thinking-details-body');
  let reasonEl = body.querySelector('.reasoning-content');
  if (!reasonEl) {
    reasonEl = document.createElement('div');
    reasonEl.className = 'reasoning-content';
    reasonEl.style.color = 'var(--text-dim)';
    reasonEl.style.fontStyle = 'italic';
    reasonEl.style.whiteSpace = 'pre-wrap';
    body.appendChild(reasonEl);
  }
  reasonEl.textContent += text;
  body.style.display = 'block';
  const arrow = thinkingEl.querySelector('.arrow');
  if (arrow) arrow.textContent = '\u25BC';
  scrollToBottom();
}

function updateProgressBar(elapsed) {
  const fill = document.querySelector('.ep-progress-fill');
  const label = document.getElementById('execElapsed');
  if (label) {
    const est = arguments.length > 1 && arguments[1] ? arguments[1] : 60;
    const remaining = Math.max(0, est - elapsed);
    label.textContent = elapsed + 's / ' + est + 's';
  }
  if (fill) {
    const est = arguments.length > 1 && arguments[1] ? arguments[1] : 60;
    const pct = Math.min(Math.floor(elapsed / est * 100), 95);
    fill.style.width = pct + '%';
  }
}

// ─── Options ───────────────────────────────────────────────────────

let _optionsCache = { thinking_collapsed_default: true };

async function fetchOptions() {
  try {
    const r = await fetch('/api/options');
    _optionsCache = await r.json();
    thinkingCollapsed = _optionsCache.thinking_collapsed_default;
  } catch (e) {}
}

async function saveOption(key, value) {
  _optionsCache[key] = value;
  if (key === 'thinking_collapsed_default') thinkingCollapsed = value;
  try {
    await fetch('/api/options', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [key]: value })
    });
  } catch (e) {}
}

function toggleOptions() {
  const panel = document.getElementById('settingsPanel');
  const chat = document.getElementById('chatArea');
  const inputArea = document.getElementById('inputArea');
  _optionsOpen = !_optionsOpen;
  if (_optionsOpen) {
    chat.style.display = 'none';
    inputArea.style.display = 'none';
    panel.style.display = 'block';
    renderSettings();
  } else {
    chat.style.display = '';
    inputArea.style.display = '';
    panel.style.display = 'none';
  }
}

function renderSettings() {
  const content = document.getElementById('settingsContent');
  content.innerHTML = `
    <div class="setting-row">
      <label for="optCollapse">Thinking details collapsed by default</label>
      <input type="checkbox" id="optCollapse"
        ${_optionsCache.thinking_collapsed_default ? 'checked' : ''}
        onchange="saveOption('thinking_collapsed_default', this.checked)">
    </div>
  `;
}

// ─── Temp Chat ─────────────────────────────────────────────────────

function toggleTempChat() {
  const main = document.getElementById('main');
  const sidebar = document.getElementById('sidebar');
  const btn = document.getElementById('tempChatBtn');
  const welcome = document.getElementById('welcome');
  const welcomeText = document.getElementById('welcomeText');
  const inputArea = document.getElementById('inputArea');

  isTempChat = !isTempChat;

  if (isTempChat) {
    _prevSessionState = {
      messagesHtml: document.getElementById('messages').innerHTML,
      welcomeDisplay: welcome.style.display,
      welcomeTextContent: welcomeText.textContent,
    };
    btn.classList.add('active');
    main.classList.add('temp-mode');
    if (!sidebar.classList.contains('collapsed')) {
      toggleSidebar();
    }
    welcome.style.display = 'flex';
    welcomeText.textContent = 'Chat without memory and history.';
    document.getElementById('messages').innerHTML = '';
    hasSentMessage = false;
    currentAssistantEl = null;
    inputArea.classList.add('welcome-input');
    document.getElementById('executionPanel').style.display = 'none';
    sendJson({ type: 'temp_session' });
  } else {
    btn.classList.remove('active');
    main.classList.remove('temp-mode');
    if (sidebar.classList.contains('collapsed')) {
      toggleSidebar();
    }
    if (_prevSessionState) {
      document.getElementById('messages').innerHTML = _prevSessionState.messagesHtml;
      welcome.style.display = _prevSessionState.welcomeDisplay;
      welcomeText.textContent = _prevSessionState.welcomeTextContent;
    }
    hasSentMessage = false;
    currentAssistantEl = null;
    inputArea.classList.remove('welcome-input');
    if (!_prevSessionState || _prevSessionState.messagesHtml) {
      hideWelcome();
    } else {
      inputArea.classList.add('welcome-input');
    }
    sendJson({ type: 'restore_session' });
  }
}

function showTodoList(items, done) {
  let todoEl = document.getElementById('todo-panel');
  if (!todoEl) {
    todoEl = document.createElement('div');
    todoEl.id = 'todo-panel';
    todoEl.className = 'todo-panel';
    const msgs = messagesEl();
    msgs.insertBefore(todoEl, msgs.firstChild);
  }
  let html = '<div class="todo-header">Task Plan</div>';
  items.forEach(item => {
    const icon = item.status === 'completed' ? '✓' : item.status === 'in_progress' ? '⏳' : ' ';
    let cls = item.status === 'completed' ? 'done' : item.status === 'in_progress' ? 'active' : '';
    html += `<div class="todo-item ${cls}"><span class="todo-icon">[${icon}]</span> ${escapeHtml(item.content)}</div>`;
  });
  todoEl.innerHTML = html;
  if (done) {
    setTimeout(() => {
      const panel = document.getElementById('todo-panel');
      if (panel) panel.style.opacity = '0.5';
    }, 1000);
  }
}

function showSubTasks(tasks) {
  if (!currentAssistantEl) {
    currentAssistantEl = createAssistantMessage();
  }
  let body = currentAssistantEl.querySelector('.thinking-details-body');
  if (!body) {
    ensureThinkingEl(true);
    toggleThinkingDetails(currentAssistantEl.querySelector('.thinking-details-header'));
    body = currentAssistantEl.querySelector('.thinking-details-body');
  }
  if (!body) return;
  let container = body.querySelector('.sub-tasks');
  if (!container) {
    container = document.createElement('div');
    container.className = 'sub-tasks';
    body.appendChild(container);
  }
  tasks.forEach(t => {
    const item = document.createElement('div');
    item.className = 'sub-task-item';
    item.setAttribute('data-sub-title', t.title);
    item.innerHTML = `<span class="sub-task-icon">⏳</span> ${escapeHtml(t.title)}`;
    container.appendChild(item);
  });
}

function updateSubTask(title, success, elapsed, tools) {
  if (!currentAssistantEl) return;
  const item = currentAssistantEl.querySelector(`.sub-task-item[data-sub-title="${title}"]`);
  if (!item) return;
  const icon = item.querySelector('.sub-task-icon');
  if (icon) icon.textContent = success ? '✓' : '✗';
  item.style.color = success ? 'var(--green)' : 'var(--red)';
  item.innerHTML = `<span class="sub-task-icon">${success ? '✓' : '✗'}</span> ${escapeHtml(title)} <span style="font-size:10px;color:var(--text-muted)">${elapsed}s · ${tools} tools</span>`;
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
  if (data.usage_supported === false) {
    summaryEl.innerHTML = `
      <span title="Usage not available">Usage not supported</span>
      <span title="Elapsed">${data.elapsed}s</span>
      ${balanceHtml}
    `;
  } else {
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
  }
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
  if ((e.key === 'End' || (e.ctrlKey && e.key === 'e')) && !input.value.trim()) {
    e.preventDefault();
    scrollToBottom();
  }
  if ((e.key === 'Home' || (e.ctrlKey && e.key === 'h')) && !input.value.trim()) {
    e.preventDefault();
    scrollToTop();
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

  const inputArea = document.getElementById('inputArea');
  if (inputArea.classList.contains('welcome-input')) {
    inputArea.classList.remove('welcome-input');
    document.getElementById('welcome').style.display = 'none';
  }

  if (_optionsOpen) {
    document.getElementById('settingsPanel').style.display = 'none';
    document.getElementById('chatArea').style.display = '';
    document.getElementById('inputArea').style.display = '';
    _optionsOpen = false;
  }

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
  document.getElementById('inputArea').classList.add('welcome-input');
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
        const st = d.querySelector('.thinking-banner-text');
        if (st) {
          const count = d.querySelectorAll('.thinking-tool-item').length;
          st.textContent = count > 0 ? `${count} tools completed` : '';
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
    const st = d.querySelector('.thinking-banner-text');
    if (st) {
      const count = d.querySelectorAll('.thinking-tool-item').length;
      st.textContent = count > 0 ? `${count} tools completed` : '';
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

  // Welcome page: center the input if welcome is visible
  const inputArea = document.getElementById('inputArea');
  if (inputArea && !hasSentMessage) {
    inputArea.classList.add('welcome-input');
  }

  // Scroll-aware input collapse
  const msgs = messagesEl();
  msgs.addEventListener('scroll', checkScrollPosition);
  document.getElementById('scrollHint').addEventListener('click', scrollToBottom);

  // Keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && _optionsOpen) {
      toggleOptions();
      return;
    }
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if (e.key === 'End' || (e.ctrlKey && e.key === 'e')) {
      e.preventDefault();
      scrollToBottom();
    }
    if (e.key === 'Home' || (e.ctrlKey && e.key === 'h')) {
      e.preventDefault();
      scrollToTop();
    }
  });
});
