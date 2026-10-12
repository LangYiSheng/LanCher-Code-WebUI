'use strict';

// 页面只订阅后端事件；关闭页面不会取消 Agent 的运行。
const $ = (id) => document.getElementById(id);
const state = {
  status: null, sessions: [], session: null, messages: new Map(), tools: new Map(),
  permissions: new Map(), events: [], lastSequence: 0, result: null, usage: {},
  files: [], selectedFile: null, fileData: null, fileView: 'content', queue: [],
  source: null, selectionGeneration: 0, fileGeneration: 0, loading: false,
  submitting: false, openTools: new Set(), renderTimer: null, filesTimer: null,
};
const EXAMPLES = {
  backend: '创建一个 Python Todo 后端项目，提供新增、查询、完成和删除任务的 API。写好测试，实际运行测试验证，并给出启动方式。',
  repair: '做一次测试失败与自主修复实验：创建一个有缺陷的 Todo 后端，先运行测试观察失败，再修复问题并重新验证。',
  permission: '做一次权限审批实验：申请执行一个需要人工批准的操作，等待我的允许或拒绝，并明确解释审批结果。',
  cancel: '做一次长任务取消实验：开始一个持续运行的任务，保留足够的时间让我点击停止，并正确完成取消收尾。',
};
const STATUS_LABELS = {
  idle: '准备就绪', ready: '准备就绪', running: '正在运行', starting: '正在启动',
  waiting_permission: '等待审批', waiting: '等待审批', awaiting_permission: '等待审批',
  completed: '已完成', cancelled: '已停止', stopped: '已停止', failed: '运行失败',
  error: '运行失败', interrupted: '运行已中断', paused: '队列已暂停', stopping: '正在停止',
};
const BUSY_STATUSES = new Set(['running', 'starting', 'waiting_permission', 'waiting', 'awaiting_permission', 'stopping']);
const EVENT_LABELS = {
  user_message_created: '任务已提交', assistant_message_started: 'Agent 开始响应',
  assistant_text_delta: '文本输出', assistant_message_completed: '响应结束',
  tool_call_started: '工具调用', tool_result_received: '工具结果', usage_updated: '用量更新',
  progress_updated: '运行进度', permission_request_created: '请求审批',
  permission_request_resolved: '审批已处理', permission_request_closed: '审批已关闭',
  turn_completed: '任务完成', turn_cancelled: '任务取消', turn_failed: '任务失败',
  pending_input_changed: '后续任务变化', steering_applied: '追加输入',
  lab_state: '会话状态', lab_log: '运行日志', lab_files_changed: '文件变化', lab_result: '运行结果',
  session_changed: '会话保存', compaction_updated: '上下文压缩',
};
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}
function stringify(value) {
  if (typeof value === 'string') return value;
  if (value === undefined || value === null) return '';
  return JSON.stringify(value, null, 2);
}
function shortText(text, max = 95) {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim();
  return normalized.length > max ? normalized.slice(0, max) + '…' : normalized;
}
function isBusy() { return !!state.session && (BUSY_STATUSES.has(state.session.status) || state.permissions.size > 0); }
function statusLabel(status) { return STATUS_LABELS[status] || status || '准备就绪'; }
function relativeDate(value) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '刚刚';
  const minutes = Math.floor((Date.now() - date.getTime()) / 60000);
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes} 分钟前`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)} 小时前`;
  return date.toLocaleDateString('zh-CN', {month: 'numeric', day: 'numeric'});
}
function timeLabel(value) {
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'}) : '';
}
function formatNumber(value) { return typeof value === 'number' ? value.toLocaleString('zh-CN') : '—'; }
function fileSize(value) {
  return Number(value) < 1024 ? `${Number(value) || 0} B` : `${(Number(value) / 1024).toFixed(1)} KB`;
}
function storeSelection(value) {
  try { localStorage.setItem('lancher-lab-session', value); } catch (_) { /* 无持久化权限时继续使用页面内状态。 */ }
}
function savedSelection() {
  try { return localStorage.getItem('lancher-lab-session'); } catch (_) { return null; }
}
async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {cache: 'no-store', ...options, headers: {'Content-Type': 'application/json', ...(options.headers || {})}});
  } catch (_) { throw new Error('无法连接实验后端。请确认服务正在运行，然后刷新状态。'); }
  const body = await response.text();
  let data;
  try { data = body ? JSON.parse(body) : null; } catch (_) {
    if (response.ok) throw new Error('后端返回了无法读取的响应。');
    data = null;
  }
  if (!response.ok) {
    const detail = data?.detail || data?.error || data?.message;
    throw new Error(typeof detail === 'string' ? detail : detail ? stringify(detail) : `请求失败（HTTP ${response.status}）。`);
  }
  return data;
}
function showError(error) {
  $('error-text').textContent = error instanceof Error ? error.message : String(error);
  $('global-error').hidden = false;
}
function clearError() { $('global-error').hidden = true; }
function toast(message, isError = false) {
  const node = element('div', `toast${isError ? ' error' : ''}`, message);
  $('toast-container').append(node);
  setTimeout(() => node.remove(), 4500);
}
function post(path, data = {}) { return api(path, {method: 'POST', body: JSON.stringify(data)}); }
function renderSessions() {
  const list = $('session-list'); list.replaceChildren();
  if (!state.sessions.length) { list.append(element('div', 'session-empty', '还没有实验会话。创建一个，开始探索。')); return; }
  list.append(element('div', 'session-section-label', '最近的实验'));
  for (const session of state.sessions) {
    const button = element('button', `session-item${session.id === state.session?.id ? ' active' : ''}`);
    button.setAttribute('aria-current', session.id === state.session?.id ? 'page' : 'false');
    button.append(element('span', 'session-icon', '▱'));
    const info = element('span', 'session-info');
    const title = element('strong', '', session.title || '未命名实验'); title.title = session.title || '未命名实验'; info.append(title);
    const meta = element('span', 'session-meta');
    meta.append(element('i', BUSY_STATUSES.has(session.status) ? 'running-dot' : ''), element('span', '', statusLabel(session.status)), element('span', '', '·'), element('span', '', relativeDate(session.created_at)));
    info.append(meta); button.append(info);
    button.addEventListener('click', () => { closeSidebar(); selectSession(session.id).catch(showError); });
    list.append(button);
  }
}
function updateSession(session) {
  if (!session) return;
  if (session.id === state.session?.id) state.session = {...state.session, ...session};
  const index = state.sessions.findIndex((item) => item.id === session.id);
  if (index >= 0) state.sessions[index] = {...state.sessions[index], ...session}; else state.sessions.unshift(session);
}
function renderHeader() {
  const session = state.session; const mode = session?.mode || 'demo';
  $('session-title').textContent = session?.title || '开始一场新实验';
  $('mode-badge').textContent = mode === 'live' ? '在线模型' : '演示模型 · 真实 Agent';
  $('mode-badge').classList.toggle('live', mode === 'live');
  $('mode-badge').title = mode === 'live' ? session?.model || '在线模型' : '确定性演示提供方驱动真实 LanCher Agent SDK';
  $('run-status').textContent = state.loading ? '读取会话中…' : state.permissions.size ? '等待你的审批' : session ? statusLabel(session.status) : '准备就绪';
  $('run-dot').className = `status-dot ${state.permissions.size ? 'amber' : ['failed', 'error'].includes(session?.status) ? 'red' : 'green'}${isBusy() && !state.permissions.size ? ' pulse' : ''}`;
  $('run-detail').textContent = session ? session.model || 'Agent 执行工作区任务' : '每一步，都看得见。';
  $('stop-button').hidden = !isBusy();
  $('composer-context').textContent = session ? (session.workspace || '').replace(/\\/g, '/').split('/').filter(Boolean).at(-1) || '独立工作区' : '独立工作区';
  $('composer-context').title = session?.workspace || '新建会话后自动创建独立工作区';
  $('send-button').disabled = state.loading || state.submitting || session?.status === 'stopping';
  $('send-label').textContent = session?.status === 'stopping' ? '收尾中…' : state.submitting ? '提交中…' : isBusy() ? '加入队列' : '发送任务';
  $('composer-hint').textContent = session?.status === 'stopping' ? 'Agent 正在停止与保存会话，收尾完成后即可继续发送。' : isBusy() ? '当前任务持续运行；新输入会加入后续任务队列。' : session ? '刷新页面不会停止任务，点击停止才会取消当前运行。' : '先选一个实验方向，或者直接输入你的任务。';
  $('workspace-path').textContent = session?.workspace || '尚未创建工作区'; $('workspace-path').title = session?.workspace || '';
}
function renderEnvironment() {
  const status = state.status; if (!status) return;
  $('server-status').textContent = '本地服务在线'; $('server-dot').className = 'status-dot green';
  $('sdk-version').textContent = `SDK ${status.sdk_version || 'snapshot'}`;
  $('sdk-version').title = status.sdk_commit ? `固定 SDK 快照：${status.sdk_commit}` : '独立 SDK 快照';
  $('isolation-note').textContent = typeof status.isolation === 'string' ? status.isolation : status.isolation?.description || 'Agent 仅访问独立实验工作区。';
  const rows = [
    ['SDK 版本', status.sdk_version || '独立快照'], ['SDK 提交', status.sdk_commit ? String(status.sdk_commit).slice(0, 12) : '未提供'],
    ['运行隔离', typeof status.isolation === 'string' ? status.isolation : stringify(status.isolation) || '独立工作区'],
    ['容器环境', status.docker_available ? 'Docker 可用' : 'Docker 未启用'],
    ['在线模型', status.live_available ? '已配置，可在新实验中选择' : '尚未配置'], ['页面重连', '刷新后读取会话快照，并续接事件流'],
  ];
  const details = $('environment-details'); details.replaceChildren();
  for (const [label, value] of rows) { const row = element('div', 'environment-row'); row.append(element('dt', '', label), element('dd', '', value)); details.append(row); }
  $('live-radio').disabled = !status.live_available;
  $('live-note').textContent = status.live_available ? '使用独立实验环境的模型配置' : '尚未配置在线模型，请先体验演示模式';
  $('new-model').replaceChildren();
  for (const model of (status.models || []).filter((item) => item.mode !== 'demo' && item.id !== 'lab/demo')) { const option = element('option', '', model.name || model.id); option.value = model.id; $('new-model').append(option); }
}

// 使用文本节点构造 Markdown，模型、文件和命令输出不能注入 HTML。
function appendInline(container, value) {
  const parts = String(value || '').split(/(`[^`\n]+`|\*\*[^*\n]+\*\*)/g);
  for (const part of parts) {
    if (part.startsWith('`') && part.endsWith('`')) container.append(element('code', '', part.slice(1, -1)));
    else if (part.startsWith('**') && part.endsWith('**')) container.append(element('strong', '', part.slice(2, -2)));
    else container.append(document.createTextNode(part));
  }
}
function markdown(value) {
  const fragment = document.createDocumentFragment();
  const lines = String(value || '').replace(/\r\n/g, '\n').split('\n');
  let paragraph = []; let list = null;
  const flushParagraph = () => {
    if (!paragraph.length) return;
    const node = element('p'); appendInline(node, paragraph.join('\n')); fragment.append(node); paragraph = [];
  };
  const flushList = () => { if (list) { fragment.append(list); list = null; } };
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (line.startsWith('```')) {
      flushParagraph(); flushList();
      const pre = element('pre'); const language = line.slice(3).trim();
      if (language) pre.append(element('span', 'code-language', language));
      const code = [];
      while (index + 1 < lines.length && !lines[index + 1].startsWith('```')) code.push(lines[++index]);
      if (index + 1 < lines.length) index += 1;
      pre.append(element('code', '', code.join('\n'))); fragment.append(pre);
    } else if (/^#{1,6}\s/.test(line)) {
      flushParagraph(); flushList();
      const heading = element('h3'); appendInline(heading, line.replace(/^#{1,6}\s/, '')); fragment.append(heading);
    } else if (/^\s*(?:[-*]|\d+\.)\s+/.test(line)) {
      flushParagraph(); const ordered = /^\s*\d+\./.test(line);
      if (list && list.tagName !== (ordered ? 'OL' : 'UL')) flushList();
      if (!list) list = element(ordered ? 'ol' : 'ul');
      const item = element('li'); appendInline(item, line.replace(/^\s*(?:[-*]|\d+\.)\s+/, '')); list.append(item);
    } else if (!line.trim()) { flushParagraph(); flushList(); }
    else { flushList(); paragraph.push(line); }
  }
  flushParagraph(); flushList(); return fragment;
}
function upsertMessage(message) {
  if (!message?.id || message.role === 'system') return;
  state.messages.set(message.id, {...(state.messages.get(message.id) || {}), ...message});
}
function importTrace(message) {
  for (const trace of message.trace?.entries || []) {
    if (!trace.call_id || !['tool_call', 'tool_result'].includes(trace.kind)) continue;
    const tool = state.tools.get(trace.call_id) || {id: trace.call_id, messageId: message.id};
    tool.name = trace.tool_name || tool.name;
    if (trace.kind === 'tool_call') tool.arguments = trace.arguments || {};
    else if (!tool.result) tool.result = {content: trace.text, is_error: trace.ok === false};
    state.tools.set(tool.id, tool);
  }
}
function toolSummary(tool) {
  const args = tool.arguments || {};
  return shortText(args.command || args.path || args.file_path || args.description || args.query || args.pattern || tool.result?.summary || stringify(args), 65);
}
function toolCard(tool) {
  const node = element('details', `tool-card${tool.result?.is_error ? ' error' : ''}`);
  node.open = state.openTools.has(tool.id) || !!tool.result?.is_error;
  node.addEventListener('toggle', () => { if (node.open) state.openTools.add(tool.id); else state.openTools.delete(tool.id); });
  const heading = element('summary'); const toolName = tool.name || '工具';
  heading.append(element('span', 'tool-glyph', /command|shell|exec|run/i.test(toolName) ? '>_' : /write|edit/i.test(toolName) ? '↗' : '⌕'));
  heading.append(element('span', 'tool-title', toolName), element('span', 'tool-summary', toolSummary(tool)));
  heading.append(element('span', `tool-status ${tool.result ? tool.result.is_error ? 'failed' : 'success' : ''}`, tool.result ? tool.result.is_error ? '失败' : '完成' : '执行中'));
  node.append(heading);
  const content = element('div', 'tool-content');
  content.append(element('h5', '', '调用参数'), element('pre', '', stringify(tool.arguments || {})));
  if (tool.result) content.append(element('h5', '', tool.result.is_error ? '错误结果' : '执行结果'), element('pre', '', tool.result.content || tool.result.error_message || tool.result.summary || '工具执行完成。'));
  node.append(content); return node;
}
function permissionCard(request) {
  const card = element('section', 'permission-card'); const heading = element('div', 'permission-heading');
  heading.append(element('span', '', '◇'), element('strong', '', request.title || '这一步需要你的审批')); card.append(heading);
  if (request.prompt || request.description) card.append(element('p', '', request.prompt || request.description));
  const command = request.command || request.details;
  if (command) card.append(element('pre', '', command));
  if (request.file_paths?.length) card.append(element('p', '', `涉及文件：${request.file_paths.join('、')}`));
  const buttons = element('div', 'permission-buttons');
  for (const [outcome, label] of [['deny', '拒绝'], ['allow', '允许本次']]) {
    const button = element('button', outcome === 'allow' ? 'permission-allow' : 'permission-deny', label);
    button.addEventListener('click', async () => {
      for (const sibling of buttons.children) sibling.disabled = true;
      try {
        await post(`/api/sessions/${state.session.id}/permissions/${encodeURIComponent(request.request_id)}`, {outcome});
        state.permissions.delete(request.request_id); scheduleRender(); toast(outcome === 'allow' ? '已批准本次操作。' : '已拒绝操作，Agent 将收到审批结果。');
      } catch (error) { showError(error); for (const sibling of buttons.children) sibling.disabled = false; }
    }); buttons.append(button);
  }
  card.append(buttons); return card;
}
function renderTimeline() {
  const timeline = $('timeline'); const nearBottom = timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight < 100;
  const scrollBefore = timeline.scrollTop; const list = $('message-list'); list.replaceChildren();
  $('welcome').hidden = state.messages.size > 0;
  for (const message of state.messages.values()) {
    const card = element('article', `message ${message.role}`); const heading = element('div', 'message-heading');
    heading.append(element('span', 'avatar', message.role === 'user' ? 'U' : 'L'), element('strong', '', message.role === 'user' ? '你' : 'LanCher Agent'));
    heading.append(element('span', 'message-time', timeLabel(message.timestamp)));
    const messageStatus = {streaming: '正在处理', complete: '', cancelled: '已取消', error: '发生错误'}[message.status] || '';
    if (messageStatus) heading.append(element('span', 'message-status', messageStatus));
    card.append(heading); const body = element('div', 'message-body');
    if (message.content) body.append(markdown(message.content));
    else if (message.status === 'streaming') body.append(element('span', 'thinking-placeholder', '正在处理任务…'));
    if (message.status === 'streaming' && isBusy()) body.append(element('span', 'streaming-cursor'));
    card.append(body);
    const tools = [...state.tools.values()].filter((tool) => tool.messageId === message.id);
    if (tools.length) { const toolList = element('div', 'tool-list'); for (const tool of tools) toolList.append(toolCard(tool)); card.append(toolList); }
    list.append(card);
  }
  const orphanTools = [...state.tools.values()].filter((tool) => !state.messages.has(tool.messageId));
  if (orphanTools.length) { const tools = element('div', 'tool-list'); for (const tool of orphanTools) tools.append(toolCard(tool)); list.append(tools); }
  for (const request of state.permissions.values()) list.append(permissionCard(request));
  if (state.result && !isBusy()) {
    const failed = ['failed', 'error'].includes(state.result.status); const cancelled = state.result.status === 'cancelled';
    const banner = element('div', `result-banner${failed ? ' error' : ''}`);
    banner.append(element('span', '', failed ? '!' : cancelled ? '■' : '✓'), element('span', '', failed ? state.result.error_text || '任务运行失败，请查看工具结果。' : cancelled ? '任务已停止，工作区与记录已保留。' : '本轮任务完成，文件与执行结果已保存。'));
    banner.append(element('small', '', `SEQ ${state.lastSequence}`)); list.append(banner);
  }
  timeline.scrollTop = nearBottom ? timeline.scrollHeight : scrollBefore;
}
function renderQueue() {
  const area = $('queue-area'); area.replaceChildren(); area.hidden = !state.queue.length;
  if (!state.queue.length) return;
  const heading = element('div', 'queue-header'); heading.append(element('strong', '', `后续任务队列 · ${state.queue.length}`));
  const paused = state.queue.some((item) => ['paused', 'stopped'].includes(item.state || item.status));
  if (paused && !isBusy()) {
    const resume = element('button', '', '继续队列 →');
    resume.addEventListener('click', async () => {
      resume.disabled = true;
      try { await post(`/api/sessions/${state.session.id}/resume`); toast('队列继续执行。'); await refreshCurrent(); }
      catch (error) { showError(error); resume.disabled = false; }
    }); heading.append(resume);
  } else heading.append(element('span', '', paused ? '已暂停' : '当前任务结束后执行'));
  area.append(heading); const list = element('div', 'queue-list');
  for (let index = 0; index < state.queue.length; index += 1) {
    const item = state.queue[index]; const row = element('div', 'queue-item'); const text = item.prompt || item.text || item.content || '';
    const description = element('p', '', text); description.title = text;
    row.append(element('span', '', String(index + 1).padStart(2, '0')), description, element('small', '', (item.state || item.status) === 'paused' ? '暂停' : '待执行')); list.append(row);
  }
  area.append(list);
}
function renderUsage() {
  const usage = state.result?.run_usage?.usage || state.result?.run_usage?.total_usage || state.result?.usage || state.usage || {};
  $('input-tokens').textContent = formatNumber(usage.input_tokens); $('output-tokens').textContent = formatNumber(usage.output_tokens);
  $('tool-count').textContent = String(state.tools.size);
  $('usage-state').textContent = state.permissions.size ? '等待审批' : isBusy() ? '运行中' : state.result ? statusLabel(state.result.status) : '等待任务';
  $('event-sequence').textContent = `SEQ ${state.lastSequence}`; $('event-count').textContent = `${state.events.length} EVENTS`;
}
function logContent(event) {
  if (event.tool_result) return event.tool_result.content || event.tool_result.error_message || event.tool_result.summary || '';
  if (event.tool_call) return `${event.tool_call.tool_name}\n${stringify(event.tool_call.arguments)}`;
  if (event.permission_request) return event.permission_request.command || event.permission_request.details || event.permission_request.prompt || '';
  if (event.kind === 'lab_result') return event.result?.error_text || event.result?.text || event.text || '';
  return event.error_text || event.progress_message || event.text || (event.kind === 'lab_state' ? statusLabel(event.session?.status) : '');
}
function renderLogs() {
  const list = $('log-list'); const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 60; list.replaceChildren();
  const logs = state.events.filter((event) => !['assistant_text_delta', 'usage_updated', 'assistant_message_started', 'assistant_message_completed'].includes(event.kind)).slice(-180);
  if (!logs.length) list.append(element('div', 'panel-empty', '真实执行事件将在这里逐条记录。'));
  for (const event of logs) {
    const row = element('div', `log-entry${event.kind === 'turn_failed' || event.tool_result?.is_error ? ' error' : ''}`);
    const heading = element('div', 'log-entry-heading'); heading.append(element('span', '', String(event.sequence || 0).padStart(3, '0')), element('span', 'log-kind', EVENT_LABELS[event.kind] || event.kind)); row.append(heading);
    const content = logContent(event); if (content) row.append(element('pre', '', content)); list.append(row);
  }
  if (nearBottom) list.scrollTop = list.scrollHeight;
}
function scheduleRender() {
  if (state.renderTimer) return;
  state.renderTimer = setTimeout(() => { state.renderTimer = null; renderHeader(); renderTimeline(); renderQueue(); renderUsage(); renderLogs(); renderSessions(); }, 70);
}

function ingestEvent(event, fromSnapshot = false) {
  if (!event || typeof event.kind !== 'string') return;
  const sequence = Number(event.sequence) || 0;
  if (!fromSnapshot && sequence > 0 && sequence <= state.lastSequence) return;
  state.lastSequence = Math.max(state.lastSequence, sequence); state.events.push(event);
  if (event.message) upsertMessage(event.message);
  else if (event.kind === 'assistant_text_delta' && event.text) {
    const last = [...state.messages.values()].filter((item) => item.role === 'assistant').at(-1);
    if (last) last.content = (last.content || '') + event.text;
  }
  if (event.tool_call) {
    const call = event.tool_call; const id = call.call_id || `tool-${sequence}`; const previous = state.tools.get(id) || {};
    state.tools.set(id, {...previous, id, name: call.tool_name, arguments: call.arguments || {}, messageId: event.message?.id || previous.messageId || [...state.messages.values()].filter((item) => item.role === 'assistant').at(-1)?.id});
  }
  if (event.tool_result) {
    const result = event.tool_result; const id = result.call_id || `tool-${sequence}`; const previous = state.tools.get(id) || {};
    state.tools.set(id, {...previous, id, name: previous.name || result.tool_name, result, messageId: previous.messageId || event.message?.id});
  }
  if (event.kind === 'permission_request_created' && event.permission_request) state.permissions.set(event.permission_request.request_id, event.permission_request);
  if (['permission_request_resolved', 'permission_request_closed'].includes(event.kind)) {
    const requestId = event.permission_resolution?.request_id || event.permission_request?.request_id;
    if (requestId) state.permissions.delete(requestId);
  }
  if (event.kind === 'usage_updated' && event.usage) state.usage = event.usage;
  if (event.kind === 'lab_state') {
    updateSession(event.session || event.state?.session);
    if (event.queue) state.queue = event.queue;
    if (event.session?.queue) state.queue = event.session.queue;
  }
  // SDK 的单轮结束可能继续执行 follow_up；宿主结果才是整项任务的终态。
  if (event.kind === 'lab_result') {
    state.result = event.result || event;
    if (state.session && state.result.status) updateSession({...state.session, status: state.result.status});
  }
  if (['turn_cancelled', 'turn_failed', 'turn_completed'].includes(event.kind)) state.permissions.clear();
  if (['user_message_created', 'assistant_message_started'].includes(event.kind)) {
    if (event.kind === 'user_message_created') state.result = null;
    if (!fromSnapshot && state.session && state.session.status !== 'stopping') updateSession({...state.session, status: 'running'});
  }
  if (event.kind === 'lab_files_changed' && !fromSnapshot) scheduleFiles();
  if (event.kind === 'pending_input_changed' && !fromSnapshot) scheduleSnapshotMetadata();
  if (!fromSnapshot) scheduleRender();
}
function setStreamStatus(label, color = '') { $('stream-status').textContent = label; $('stream-dot').className = `status-dot ${color}`; }
function connectStream(id, generation) {
  state.source?.close();
  const source = new EventSource(`/api/sessions/${encodeURIComponent(id)}/events?after=${state.lastSequence}`); state.source = source;
  setStreamStatus('连接事件流…', 'amber');
  source.onopen = () => { if (generation === state.selectionGeneration) setStreamStatus('事件流已连接', 'green'); };
  source.onmessage = (message) => {
    if (generation !== state.selectionGeneration) return;
    try { ingestEvent(JSON.parse(message.data)); }
    catch (error) { console.warn('无法读取事件', error); setStreamStatus('事件解析异常', 'red'); }
  };
  source.onerror = () => { if (generation === state.selectionGeneration) setStreamStatus('连接中断，自动重连…', 'amber'); };
}
function clearSessionData() {
  state.messages.clear(); state.tools.clear(); state.permissions.clear(); state.openTools.clear();
  state.events = []; state.lastSequence = 0; state.result = null; state.usage = {};
  state.files = []; state.selectedFile = null; state.fileData = null; state.queue = [];
}
async function selectSession(id) {
  const generation = ++state.selectionGeneration; state.source?.close(); state.source = null;
  state.loading = true; clearError(); clearSessionData();
  state.session = state.sessions.find((item) => item.id === id) || {id, title: '读取实验…', status: 'idle'};
  renderHeader(); renderSessions(); renderTimeline(); renderFiles(); renderFilePreview(); renderQueue(); renderUsage(); renderLogs();
  try {
    const snapshot = await api(`/api/sessions/${encodeURIComponent(id)}`);
    if (generation !== state.selectionGeneration) return;
    state.session = snapshot; updateSession(snapshot);
    for (const event of snapshot.events || []) ingestEvent(event, true);
    for (const message of snapshot.messages || []) { upsertMessage(message); importTrace(message); }
    state.permissions.clear();
    for (const request of snapshot.pending_permissions || []) state.permissions.set(request.request_id, request);
    state.result = snapshot.result || state.result; state.queue = snapshot.queue || [];
    state.files = Array.isArray(snapshot.files) ? snapshot.files : snapshot.files?.files || [];
    state.lastSequence = Math.max(state.lastSequence, Number(snapshot.last_sequence || snapshot.sequence) || 0);
    storeSelection(id); state.loading = false;
    renderHeader(); renderSessions(); renderTimeline(); renderFiles(); renderQueue(); renderUsage(); renderLogs();
    connectStream(id, generation);
    if (state.files.length) await selectFile(state.files[0].path); else await loadFiles();
  } catch (error) {
    if (generation !== state.selectionGeneration) return;
    state.loading = false; renderHeader(); setStreamStatus('无法读取会话', 'red'); throw error;
  }
}
async function refreshCurrent() {
  if (state.session) return selectSession(state.session.id);
  const [status, sessions] = await Promise.all([api('/api/status'), api('/api/sessions')]);
  state.status = status; state.sessions = Array.isArray(sessions) ? sessions : sessions.sessions || [];
  renderEnvironment(); renderSessions(); renderHeader();
}
let metadataTimer;
function scheduleSnapshotMetadata() {
  clearTimeout(metadataTimer); const id = state.session?.id; const generation = state.selectionGeneration;
  metadataTimer = setTimeout(async () => {
    try {
      const snapshot = await api(`/api/sessions/${id}`);
      if (generation !== state.selectionGeneration) return;
      state.queue = snapshot.queue || []; updateSession(snapshot); scheduleRender();
    } catch (_) { /* 事件流会继续重试；只读补充失败无需中断运行。 */ }
  }, 250);
}
function renderFiles() {
  $('file-count').textContent = String(state.files.length); const tree = $('file-tree'); tree.replaceChildren();
  if (!state.files.length) {
    const empty = element('div', 'empty-files'); empty.append(element('span', '', '▱'));
    const message = element('p', '', 'Agent 生成的文件\n会出现在这里。'); message.style.whiteSpace = 'pre-line'; empty.append(message); tree.append(empty); return;
  }
  for (const file of [...state.files].sort((a, b) => a.path.localeCompare(b.path))) {
    const row = element('button', `file-row${file.path === state.selectedFile ? ' active' : ''}`); row.title = file.path; row.setAttribute('aria-label', `打开文件 ${file.path}`);
    const extension = file.path.split('.').at(-1).toLowerCase();
    row.append(element('span', `file-ext ${extension.replace(/[^a-z]/g, '')}`, extension.slice(0, 3)), element('span', 'file-name', file.path));
    if (file.status && file.status !== 'unchanged') row.append(element('span', `file-status ${file.status}`, file.status === 'added' ? 'A' : file.status === 'deleted' ? 'D' : 'M'));
    row.append(element('span', 'file-size', fileSize(file.size))); row.addEventListener('click', () => selectFile(file.path).catch(showError)); tree.append(row);
  }
}
async function loadFiles() {
  if (!state.session) return;
  const id = state.session.id; const generation = state.selectionGeneration; const response = await api(`/api/sessions/${id}/files`);
  if (generation !== state.selectionGeneration) return;
  state.files = Array.isArray(response) ? response : response.files || []; renderFiles();
  if (state.selectedFile && state.files.some((file) => file.path === state.selectedFile)) await selectFile(state.selectedFile);
  else if (state.files.length) await selectFile(state.files[0].path);
  else { state.selectedFile = null; state.fileData = null; renderFilePreview(); }
}
function scheduleFiles() { clearTimeout(state.filesTimer); state.filesTimer = setTimeout(() => loadFiles().catch(showError), 250); }
async function selectFile(path) {
  if (!state.session) return;
  const sessionGeneration = state.selectionGeneration; const generation = ++state.fileGeneration;
  state.selectedFile = path; state.fileData = null; renderFiles();
  $('preview-name').textContent = path.split('/').at(-1); $('preview-name').title = path;
  $('code-view').replaceChildren(element('div', 'file-loading', '正在读取文件…'));
  try {
    const data = await api(`/api/sessions/${state.session.id}/file?path=${encodeURIComponent(path)}`);
    if (sessionGeneration !== state.selectionGeneration || generation !== state.fileGeneration) return;
    state.fileData = data; renderFilePreview();
  } catch (error) {
    if (sessionGeneration !== state.selectionGeneration || generation !== state.fileGeneration) return;
    $('code-view').replaceChildren(element('div', 'file-error', error.message));
  }
}
function renderFilePreview() {
  $('content-tab').classList.toggle('active', state.fileView === 'content'); $('diff-tab').classList.toggle('active', state.fileView === 'diff');
  $('content-tab').setAttribute('aria-selected', String(state.fileView === 'content')); $('diff-tab').setAttribute('aria-selected', String(state.fileView === 'diff'));
  const view = $('code-view'); view.replaceChildren();
  if (!state.fileData) {
    $('preview-name').textContent = state.selectedFile || '文件预览'; const empty = element('div', 'preview-empty'); empty.append(element('span', '', '⌘'));
    const text = element('p', '', '选择一个文件，\n看看 Agent 写了什么。'); text.style.whiteSpace = 'pre-line'; empty.append(text); view.append(empty); return;
  }
  $('preview-name').textContent = state.selectedFile.split('/').at(-1); $('preview-name').title = state.selectedFile;
  const data = state.fileView === 'diff' ? state.fileData.diff || '' : state.fileData.content || '';
  if (!data) { view.append(element('div', 'file-loading', state.fileView === 'diff' ? '这个文件与基线一致，没有变化。' : '这个文件是空的。')); return; }
  const code = element('div', 'code-lines'); const lines = (Array.isArray(data) ? data.join('\n') : String(data)).replace(/\r\n/g, '\n').split('\n');
  lines.forEach((text, index) => {
    let className = 'code-line';
    if (state.fileView === 'diff') {
      if (text.startsWith('+++') || text.startsWith('---')) className += ' diff-header';
      else if (text.startsWith('+')) className += ' diff-add'; else if (text.startsWith('-')) className += ' diff-remove'; else if (text.startsWith('@@')) className += ' diff-hunk';
    }
    const row = element('div', className); row.append(element('span', 'line-number', state.fileView === 'content' ? index + 1 : ''), element('span', 'line-text', text || ' ')); code.append(row);
  }); view.append(code);
}

async function createSession({title, mode = 'demo', model} = {}) {
  const session = await post('/api/sessions', {title: title || undefined, mode, model: model || undefined});
  updateSession(session); await selectSession(session.id); return session;
}
function openNewDialog() {
  $('new-title').value = ''; document.querySelector('input[name="mode"][value="demo"]').checked = true;
  $('model-field').hidden = true; $('new-dialog').showModal(); setTimeout(() => $('new-title').focus(), 30);
}
function closeSidebar() { $('sidebar').classList.remove('open'); $('sidebar-scrim').hidden = true; }
function bindControls() {
  $('dismiss-error').addEventListener('click', clearError); $('new-session').addEventListener('click', openNewDialog);
  $('environment-button').addEventListener('click', () => $('environment-dialog').showModal());
  $('refresh-button').addEventListener('click', async () => {
    $('refresh-button').disabled = true;
    try { await refreshCurrent(); toast('已刷新实验状态。'); } catch (error) { showError(error); }
    finally { $('refresh-button').disabled = false; }
  });
  $('reload-files').addEventListener('click', () => loadFiles().catch(showError));
  $('stop-button').addEventListener('click', async () => {
    const id = state.session?.id; if (!id) return;
    $('stop-button').disabled = true;
    try { await post(`/api/sessions/${id}/stop`); toast('已发送停止请求，正在等待 Agent 收尾。'); }
    catch (error) { showError(error); } finally { $('stop-button').disabled = false; }
  });
  $('mobile-menu').addEventListener('click', () => { $('sidebar').classList.add('open'); $('sidebar-scrim').hidden = false; });
  $('sidebar-scrim').addEventListener('click', closeSidebar);
  document.querySelectorAll('[data-close]').forEach((button) => button.addEventListener('click', () => $(button.dataset.close).close()));
  document.querySelectorAll('dialog').forEach((dialog) => dialog.addEventListener('click', (event) => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  }));
  document.querySelectorAll('[data-example]').forEach((button) => button.addEventListener('click', () => { $('prompt').value = EXAMPLES[button.dataset.example]; $('prompt').focus(); resizePrompt(); }));
  document.querySelectorAll('input[name="mode"]').forEach((radio) => radio.addEventListener('change', () => { $('model-field').hidden = document.querySelector('input[name="mode"]:checked').value !== 'live'; }));
  document.querySelectorAll('[data-panel]').forEach((tab) => tab.addEventListener('click', () => {
    const panel = tab.dataset.panel; $('files-panel').hidden = panel !== 'files'; $('logs-panel').hidden = panel !== 'logs';
    for (const sibling of document.querySelectorAll('[data-panel]')) { const selected = sibling === tab; sibling.classList.toggle('active', selected); sibling.setAttribute('aria-selected', String(selected)); }
  }));
  document.querySelectorAll('[data-view]').forEach((tab) => tab.addEventListener('click', () => { state.fileView = tab.dataset.view; renderFilePreview(); }));
  $('new-session-form').addEventListener('submit', async (event) => {
    event.preventDefault(); $('create-button').disabled = true; clearError();
    try {
      const mode = document.querySelector('input[name="mode"]:checked').value;
      await createSession({title: $('new-title').value.trim(), mode, model: mode === 'live' ? $('new-model').value : undefined});
      $('new-dialog').close(); closeSidebar(); $('prompt').focus(); toast('新实验已准备好。');
    } catch (error) { showError(error); toast(error.message, true); }
    finally { $('create-button').disabled = false; }
  });
  $('composer-form').addEventListener('submit', async (event) => {
    event.preventDefault(); const prompt = $('prompt').value.trim();
    if (!prompt || state.loading || state.submitting || state.session?.status === 'stopping') { if (!prompt) $('prompt').focus(); return; }
    state.submitting = true; clearError(); renderHeader();
    try {
      if (!state.session) await createSession({title: shortText(prompt, 27), mode: 'demo'});
      const queued = isBusy();
      await post(`/api/sessions/${state.session.id}/${queued ? 'queue' : 'turns'}`, {prompt});
      if ($('prompt').value.trim() === prompt) { $('prompt').value = ''; resizePrompt(); }
      if (queued) { toast('任务已加入后续队列。'); scheduleSnapshotMetadata(); }
      else { state.result = null; updateSession({...state.session, status: 'running'}); scheduleRender(); }
    } catch (error) { showError(error); }
    finally { state.submitting = false; renderHeader(); }
  });
  $('prompt').addEventListener('input', resizePrompt);
  $('prompt').addEventListener('keydown', (event) => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); $('composer-form').requestSubmit(); } });
  document.addEventListener('keydown', (event) => {
    const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName);
    if (!typing && !event.ctrlKey && !event.metaKey && !event.altKey && event.key.toLowerCase() === 'n' && !document.querySelector('dialog[open]')) { event.preventDefault(); openNewDialog(); }
    if (event.key === 'Escape') closeSidebar();
  });
  window.addEventListener('beforeunload', () => state.source?.close());
}
function resizePrompt() { $('prompt').style.height = 'auto'; $('prompt').style.height = `${Math.min(170, Math.max(52, $('prompt').scrollHeight))}px`; }
async function boot() {
  bindControls();
  try {
    const [status, sessions] = await Promise.all([api('/api/status'), api('/api/sessions')]);
    state.status = status; state.sessions = Array.isArray(sessions) ? sessions : sessions.sessions || [];
    renderEnvironment(); renderSessions(); renderHeader();
    const previous = new URLSearchParams(location.search).get('session') || savedSelection(); const selected = state.sessions.find((session) => session.id === previous) || state.sessions[0];
    if (selected) await selectSession(selected.id);
  } catch (error) {
    $('server-status').textContent = '后端连接失败'; $('server-dot').className = 'status-dot red';
    $('isolation-note').textContent = '请先启动独立实验后端。'; showError(error);
  }
}
boot();





