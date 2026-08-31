/* =============================================
   Mahoraga Dashboard — Frontend Logic (v4-autonomous)
   =============================================
   The dashboard is a pure view into the server's state.
   Closing and reopening the browser fully restores everything.

   PERFORMANCE: All DOM updates are throttled and batched to
   prevent browser freezing/crashing during high-throughput jobs.
   ============================================= */
let proxyMode = 'none'; // none | list | api | single
let rentryMode = 'add'; // add | new
const API = {
  domains: '/api/domains',
  start: '/api/start',
  pause: '/api/pause',
  resume: '/api/resume',
  stop: '/api/stop',
  status: '/api/status',
  fullState: '/api/full_state',
  export: '/api/export',
};

// ---------- Constants ----------
const MAX_DOM_RESULT_ROWS = 10;   // Max result rows in the DOM at any time
const MAX_DOM_LOG_LINES = 50;     // Max log lines in the DOM at any time
const UI_THROTTLE_MS = 250;       // Min ms between UI updates from WebSocket

// ---------- State ----------
let jobState = 'idle'; // idle | running | paused | completed | stopped
let allDomains = [];
let domainsLoaded = false; // flag to track when domains are rendered

// ---------- Throttle State ----------
let _pendingUpdate = null;        // Queued status_update data
let _updateScheduled = false;     // Whether a rAF is pending
let _lastUpdateTime = 0;          // Timestamp of last applied update

// ---------- Socket.IO ----------
const socket = io();

socket.on('connect', () => {
  addLog('info', 'Connected to server via WebSockets.');
});

// ---------- DOM Refs ----------
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const els = {};

document.addEventListener('DOMContentLoaded', () => {
  els.emailInput = $('#email-input');
  els.emailCount = $('#email-count');
  els.domainSearch = $('#domain-search');
  els.domainList = $('#domain-list');
  els.threadSize = $('#thread-size');
  els.btnStart = $('#btn-start');
  els.btnPause = $('#btn-pause');
  els.btnStop = $('#btn-stop');
  els.progressBar = $('#progress-bar-fill');
  els.progressPercent = $('#progress-percent');
  els.progressText = $('#progress-text');
  els.statTotal = $('#stat-total');
  els.statSuccess = $('#stat-success');
  els.statNotFound = $('#stat-not-found');
  els.statRateLimit = $('#stat-rate-limit');
  els.statErrors = $('#stat-errors');
  els.resultsBody = $('#results-body');
  els.resultsEmpty = $('#results-empty');
  els.logConsole = $('#log-console');
  els.statusDot = $('#status-dot');
  els.statusText = $('#status-text');
  els.ratePerMinute = $('#rate-per-minute');
  els.ratePerHour = $('#rate-per-hour');
  els.ratePerDay = $('#rate-per-day');
  els.ratePerWeek = $('#rate-per-week');

  initEventListeners();
  loadDomains();
  updateButtonStates();
  initProxyTabs();
  initRentryMode();
});



// ---------- Init ----------
function initEventListeners() {
  els.emailInput.addEventListener('input', updateEmailCount);
  els.domainSearch.addEventListener('input', filterDomains);
  els.btnStart.addEventListener('click', startJob);
  els.btnPause.addEventListener('click', togglePause);
  els.btnStop.addEventListener('click', stopJob);

  $('#btn-select-all').addEventListener('click', () => toggleAllDomains(true));
  $('#btn-deselect-all').addEventListener('click', () => toggleAllDomains(false));
  $('#btn-select-valid').addEventListener('click', () => selectDomainGroup(validGroupDomains));
  $('#btn-select-fast').addEventListener('click', () => selectDomainGroup(fastDomains));

  // Export buttons
  $$('.btn-export').forEach(btn => {
    btn.addEventListener('click', () => {
      const type = btn.dataset.type;
      const format = btn.dataset.format;
      exportResults(type, format);
    });
  });

  // Proxy list line counter
  const proxyListInput = $('#proxy-list-input');
  if (proxyListInput) {
    proxyListInput.addEventListener('input', () => {
      const text = proxyListInput.value.trim();
      const count = text ? text.split('\n').filter(l => l.trim()).length : 0;
      $('#proxy-count').textContent = `${count} prox${count !== 1 ? 'ies' : 'y'}`;
    });
  }
}

function updateEmailCount() {
  const text = els.emailInput.value.trim();
  const count = text ? text.split('\n').filter(l => l.trim()).length : 0;
  els.emailCount.textContent = `${count} email${count !== 1 ? 's' : ''}`;
}

// ---------- Proxy Tabs ----------
function initProxyTabs() {
  $$('.proxy-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      // Skip rentry mode buttons handled separately
      if (tab.id === 'btn-rentry-add' || tab.id === 'btn-rentry-new') return;
      $$('.proxy-tab').forEach(t => {
        if (t.id !== 'btn-rentry-add' && t.id !== 'btn-rentry-new') t.classList.remove('active');
      });
      tab.classList.add('active');
      proxyMode = tab.dataset.mode;

      $$('.proxy-panel').forEach(p => p.style.display = 'none');
      if (proxyMode !== 'none') {
        const panel = $(`#proxy-panel-${proxyMode}`);
        if (panel) panel.style.display = 'block';
      }
    });
  });
}

// ---------- Rentry Add/New Toggle ----------
function initRentryMode() {
  const btnAdd = $('#btn-rentry-add');
  const btnNew = $('#btn-rentry-new');
  if (btnAdd && btnNew) {
    btnAdd.addEventListener('click', () => {
      rentryMode = 'add';
      btnAdd.classList.add('active');
      btnNew.classList.remove('active');
    });
    btnNew.addEventListener('click', () => {
      rentryMode = 'new';
      btnNew.classList.add('active');
      btnAdd.classList.remove('active');
    });
  }
}

function getProxyConfig() {
  if (proxyMode === 'none') {
    return { mode: 'none' };
  } else if (proxyMode === 'list') {
    const text = ($('#proxy-list-input') || {}).value || '';
    const proxies = text.split('\n').map(l => l.trim()).filter(l => l);
    return { mode: 'list', proxies };
  } else if (proxyMode === 'api') {
    const url = ($('#proxy-api-input') || {}).value || '';
    return { mode: 'api', api_url: url };
  } else if (proxyMode === 'single') {
    const proxy = ($('#proxy-single-input') || {}).value || '';
    return { mode: 'single', proxy };
  }
  return { mode: 'none' };
}

/**
 * Restore proxy config UI from server state.
 */
function restoreProxyConfig(proxyConfig) {
  if (!proxyConfig) return;
  const mode = proxyConfig.mode || 'none';
  proxyMode = mode;

  $$('.proxy-tab').forEach(t => {
    if (t.id !== 'btn-rentry-add' && t.id !== 'btn-rentry-new') t.classList.remove('active');
  });
  const tab = $(`#proxy-tab-${mode}`);
  if (tab) tab.classList.add('active');

  $$('.proxy-panel').forEach(p => p.style.display = 'none');
  if (mode !== 'none') {
    const panel = $(`#proxy-panel-${mode}`);
    if (panel) panel.style.display = 'block';
  }

  if (mode === 'list' && proxyConfig.proxies) {
    const input = $('#proxy-list-input');
    if (input) {
      input.value = proxyConfig.proxies.join('\n');
      const count = proxyConfig.proxies.length;
      $('#proxy-count').textContent = `${count} prox${count !== 1 ? 'ies' : 'y'}`;
    }
  } else if (mode === 'api' && proxyConfig.api_url) {
    const input = $('#proxy-api-input');
    if (input) input.value = proxyConfig.api_url;
  } else if (mode === 'single' && proxyConfig.proxy) {
    const input = $('#proxy-single-input');
    if (input) input.value = proxyConfig.proxy;
  }
}

// ---------- Domains ----------
async function loadDomains() {
  try {
    const res = await fetch(API.domains);
    const data = await res.json();
    allDomains = data.domains;
    renderDomains(data.grouped);
    domainsLoaded = true;
  } catch (e) {
    addLog('error', `Failed to load domains: ${e.message}`);
  }
}

const validGroupDomains = [
  "gravatar", "insightly.com", "flot", "freelancer", "seoclerks", "duolingo",
  "laposte", "mail_ru", "flickr", "sporcle", "caringbridge", "spotify", "xvideos",
  "anydo", "devrant", "armurerieauxerre", "amazon", "dominosfr", "envato", "naturabuy",
  "fanpop", "parler", "plurk", "taringa", "tellonym", "wattpad", "archive", "docker",
  "office365", "bodybuilding", "teamtreehouse", "rambler", "zoho"
];

// Fast mode: only amazon + office365 (default selection)
const fastDomains = ["amazon", "office365"];

function renderDomains(grouped) {
  els.domainList.innerHTML = '';
  for (const [category, domains] of Object.entries(grouped)) {
    const catLabel = document.createElement('div');
    catLabel.className = 'domain-category';
    catLabel.textContent = category.replace(/_/g, ' ');
    els.domainList.appendChild(catLabel);

    for (const d of domains) {
      const isDefault = fastDomains.includes(d.name) || fastDomains.includes(d.domain);
      const checkedAttr = isDefault ? 'checked' : '';

      const item = document.createElement('label');
      item.className = 'domain-item';
      item.dataset.name = d.name;
      item.dataset.domain = d.domain;
      item.innerHTML = `
        <input type="checkbox" value="${d.name}" ${checkedAttr}>
        <span class="domain-name">${d.name}</span>
        <span class="domain-url">${d.domain}</span>
      `;
      els.domainList.appendChild(item);
    }
  }
}

function filterDomains() {
  const q = els.domainSearch.value.toLowerCase();
  $$('.domain-item').forEach(item => {
    const name = item.dataset.name.toLowerCase();
    const domain = item.dataset.domain.toLowerCase();
    const match = !q || name.includes(q) || domain.includes(q);
    item.classList.toggle('hidden', !match);
  });
  $$('.domain-category').forEach(cat => {
    let next = cat.nextElementSibling;
    let hasVisible = false;
    while (next && !next.classList.contains('domain-category')) {
      if (!next.classList.contains('hidden')) hasVisible = true;
      next = next.nextElementSibling;
    }
    cat.style.display = hasVisible ? '' : 'none';
  });
}

function toggleAllDomains(checked) {
  $$('.domain-item input[type="checkbox"]').forEach(cb => {
    cb.checked = checked;
  });
}

/**
 * Select only domains in the given group list.
 */
function selectDomainGroup(groupList) {
  const groupSet = new Set(groupList);
  $$('.domain-item input[type="checkbox"]').forEach(cb => {
    cb.checked = groupSet.has(cb.value);
  });
}

function getSelectedDomains() {
  const selected = [];
  $$('.domain-item input[type="checkbox"]:checked').forEach(cb => {
    selected.push(cb.value);
  });
  return selected;
}

/**
 * Restore domain selections from a list of domain names.
 */
function restoreDomainSelections(selectedDomains) {
  if (!selectedDomains || selectedDomains.length === 0) return;
  const selectedSet = new Set(selectedDomains);
  $$('.domain-item input[type="checkbox"]').forEach(cb => {
    cb.checked = selectedSet.has(cb.value);
  });
}

// ---------- Job Control ----------
async function startJob() {
  const emailText = els.emailInput.value.trim();
  if (!emailText) {
    addLog('error', 'Please enter at least one email address.');
    return;
  }

  const emails = emailText.split('\n').map(l => l.trim()).filter(l => l);
  const domains = getSelectedDomains();
  if (domains.length === 0) {
    addLog('error', 'Please select at least one domain.');
    return;
  }

  const threadSize = parseInt(els.threadSize.value) || 50;
  const proxyConfig = getProxyConfig();

  if (proxyConfig.mode === 'list' && (!proxyConfig.proxies || proxyConfig.proxies.length === 0)) {
    addLog('error', 'Proxy List mode selected but no proxies provided.');
    return;
  }
  if (proxyConfig.mode === 'api' && !proxyConfig.api_url) {
    addLog('error', 'Proxy API mode selected but no URL provided.');
    return;
  }
  if (proxyConfig.mode === 'single' && !proxyConfig.proxy) {
    addLog('error', 'Single IP mode selected but no proxy provided.');
    return;
  }

  try {
    console.log("[DEBUG] Sending POST to /api/start...");
    const res = await fetch(API.start, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        emails,
        domains,
        thread_size: threadSize,
        proxy: proxyConfig,
        rentry_mode: rentryMode,
        email_text: emailText,
      }),
    });

    const rawText = await res.text();
    console.log(`[DEBUG] /api/start response: ${res.status}`, rawText);

    let data;
    try {
      data = JSON.parse(rawText);
    } catch (e) {
      addLog('error', `Server returned invalid JSON: ${rawText}`);
      return;
    }

    if (data.error) {
      addLog('error', data.error);
      return;
    }
    resetMonitoring();
    setJobState('running');
    addLog('info', `Job started — ${emails.length} emails × ${domains.length} domains, batch size ${threadSize}`);
    if (data.version) {
      addLog('info', `[SERVER] Version: ${data.version}`);
    }
  } catch (e) {
    addLog('error', `Failed to start job: ${e.message}`);
  }
}

async function togglePause() {
  const endpoint = jobState === 'paused' ? API.resume : API.pause;
  try {
    const res = await fetch(endpoint, { method: 'POST' });
    const data = await res.json();
    if (data.status === 'paused') {
      setJobState('paused');
      addLog('warn', 'Job paused.');
    } else if (data.status === 'running') {
      setJobState('running');
      addLog('info', 'Job resumed.');
    }
  } catch (e) {
    addLog('error', `Pause/Resume failed: ${e.message}`);
  }
}

async function stopJob() {
  try {
    await fetch(API.stop, { method: 'POST' });
    setJobState('stopped');
    addLog('warn', 'Job stopped by user.');
  } catch (e) {
    addLog('error', `Stop failed: ${e.message}`);
  }
}

// ============================================================
//  FULL STATE RESTORE — the "never closed" feature
// ============================================================

/**
 * Called when the server sends 'full_state' on connect/reconnect.
 * Restores the entire dashboard: config, progress, stats, logs, results.
 */
function handleFullState(data) {
  console.log('[RESTORE] Received full state from server:', data.state);

  // 1. Restore job state
  setJobState(data.state);

  // 2. Restore progress
  updateProgress(data.progress);

  // 3. Restore stats
  updateStatsImmediate(data.stats);

  // 4. Restore rates
  updateRatesImmediate(data.rates);

  // 5. Restore config (emails, domains, settings)
  if (data.config) {
    if (data.config.email_text) {
      els.emailInput.value = data.config.email_text;
      updateEmailCount();
    }
    if (data.config.thread_size) {
      els.threadSize.value = data.config.thread_size;
    }

    restoreProxyConfig(data.config.proxy);

    // Restore domain selections (with retry if domains haven't loaded yet)
    if (data.config.selected_domains && data.config.selected_domains.length > 0) {
      if (domainsLoaded) {
        restoreDomainSelections(data.config.selected_domains);
      } else {
        const retryRestore = () => {
          if (domainsLoaded) {
            restoreDomainSelections(data.config.selected_domains);
          } else {
            setTimeout(retryRestore, 200);
          }
        };
        setTimeout(retryRestore, 200);
      }
    }
  }

  // 6. Restore results (pre-trimmed by server to last 200)
  els.resultsBody.innerHTML = '';
  if (data.all_results && data.all_results.length > 0) {
    // Only render the last MAX_DOM_RESULT_ROWS to keep DOM light
    const toRender = data.all_results.slice(-MAX_DOM_RESULT_ROWS);
    appendResultsDirect(toRender);
  }

  // 7. Restore logs (pre-trimmed by server to last 200)
  els.logConsole.innerHTML = '';
  if (data.all_logs && data.all_logs.length > 0) {
    // Only render the last MAX_DOM_LOG_LINES
    const toRender = data.all_logs.slice(-MAX_DOM_LOG_LINES);
    toRender.forEach(log => addLogLineDirect(log.level, log.message, log.time));
  }

  // 8. Update input disabled states
  updateInputStates();

  console.log('[RESTORE] Full state restore complete');
}

// Listen for full_state from server (on connect/reconnect)
socket.on('full_state', (data) => {
  handleFullState(data);
});

// ============================================================
//  THROTTLED WEBSOCKET HANDLER
//  Prevents rapid-fire DOM updates from causing browser freeze
// ============================================================

socket.on('status_update', (data) => {
  // Merge new data into pending update (latest wins for stats/progress)
  if (!_pendingUpdate) {
    _pendingUpdate = {
      state: data.state,
      progress: data.progress,
      stats: data.stats,
      rates: data.rates,
      new_logs: [],
      new_results: [],
    };
  } else {
    _pendingUpdate.state = data.state;
    _pendingUpdate.progress = data.progress;
    _pendingUpdate.stats = data.stats;
    _pendingUpdate.rates = data.rates;
  }

  // Accumulate new results and logs
  if (data.new_results && data.new_results.length > 0) {
    _pendingUpdate.new_results.push(...data.new_results);
  }
  if (data.new_logs && data.new_logs.length > 0) {
    _pendingUpdate.new_logs.push(...data.new_logs);
  }

  // Schedule a batched DOM update via requestAnimationFrame
  if (!_updateScheduled) {
    _updateScheduled = true;
    requestAnimationFrame(applyPendingUpdate);
  }
});

/**
 * Apply the accumulated pending update to the DOM.
 * Uses requestAnimationFrame to batch with the browser's render cycle.
 */
function applyPendingUpdate() {
  _updateScheduled = false;

  const now = performance.now();
  // Throttle: skip if called too soon (let the next rAF handle it)
  if (now - _lastUpdateTime < UI_THROTTLE_MS && _pendingUpdate) {
    _updateScheduled = true;
    requestAnimationFrame(applyPendingUpdate);
    return;
  }
  _lastUpdateTime = now;

  const data = _pendingUpdate;
  if (!data) return;
  _pendingUpdate = null;

  // Update simple numeric displays (cheap)
  updateProgress(data.progress);
  updateStatsImmediate(data.stats);
  updateRatesImmediate(data.rates);

  // Append new results (capped before DOM insertion)
  if (data.new_results.length > 0) {
    // Only render the latest MAX_DOM_RESULT_ROWS from the batch
    const toRender = data.new_results.slice(-MAX_DOM_RESULT_ROWS);
    appendResultsDirect(toRender);
  }

  // Append new logs (capped before DOM insertion)
  if (data.new_logs.length > 0) {
    const toRender = data.new_logs.slice(-MAX_DOM_LOG_LINES);
    toRender.forEach(log => addLogLineDirect(log.level, log.message, log.time));
  }

  // State transitions
  if (data.state === 'completed') {
    if (jobState !== 'completed') {
      setJobState('completed');
      addLog('success', `Job completed! Processed ${data.stats.total} checks.`);
    }
  } else if (data.state === 'stopped') {
    if (jobState !== 'stopped') setJobState('stopped');
  } else if (data.state === 'paused') {
    if (jobState !== 'paused') setJobState('paused');
  } else if (data.state === 'running') {
    if (jobState !== 'running') setJobState('running');
  }
}

// ============================================================
//  UI UPDATE FUNCTIONS (Performance-safe)
// ============================================================

function updateProgress(progress) {
  if (!progress) return;
  const rawPct = progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0;
  const pct = Math.min(rawPct, 100);  // NEVER exceed 100%
  els.progressBar.style.width = `${pct}%`;
  els.progressPercent.textContent = `${pct}%`;
  els.progressText.innerHTML = `<strong>${progress.done}</strong> / ${progress.total} emails processed`;

  if (jobState === 'running') {
    els.progressBar.classList.add('animate');
  } else {
    els.progressBar.classList.remove('animate');
  }
}

/**
 * Update stat counters without animation (for batched/throttled updates).
 */
function updateStatsImmediate(stats) {
  if (!stats) return;
  setCounter(els.statTotal, stats.total);
  setCounter(els.statSuccess, stats.exists);
  setCounter(els.statNotFound, stats.not_found);
  setCounter(els.statRateLimit, stats.rate_limit);
  setCounter(els.statErrors, stats.errors);
}

function setCounter(el, value) {
  const current = parseInt(el.textContent) || 0;
  if (current !== value) {
    el.textContent = value;
  }
}

function formatRate(value) {
  if (value >= 1000000) return (value / 1000000).toFixed(1) + 'M';
  if (value >= 1000) return (value / 1000).toFixed(1) + 'K';
  if (Number.isInteger(value)) return value.toString();
  return value.toFixed(1);
}

/**
 * Update rate counters without animation (for batched/throttled updates).
 */
function updateRatesImmediate(rates) {
  if (!rates) return;
  setRateCounter(els.ratePerMinute, rates.per_minute);
  setRateCounter(els.ratePerHour, rates.per_hour);
  setRateCounter(els.ratePerDay, rates.per_day);
  setRateCounter(els.ratePerWeek, rates.per_week);
}

function setRateCounter(el, value) {
  const formatted = formatRate(value);
  if (el.textContent !== formatted) {
    el.textContent = formatted;
  }
}

/**
 * Append result rows to the DOM. Pre-trims input to MAX_DOM_RESULT_ROWS
 * before creating any DOM nodes, preventing unnecessary node creation.
 */
function appendResultsDirect(results) {
  if (!results || results.length === 0) return;

  if (els.resultsEmpty) {
    els.resultsEmpty.style.display = 'none';
  }

  // Pre-trim: only create DOM nodes for what we'll actually keep
  const maxNew = MAX_DOM_RESULT_ROWS;
  const toCreate = results.length > maxNew ? results.slice(-maxNew) : results;

  const fragment = document.createDocumentFragment();
  for (const r of toCreate) {
    const tr = document.createElement('tr');
    tr.className = 'fade-in';

    let statusClass = 'not-found';
    let statusLabel = 'Not Found';
    if (r.exists) {
      statusClass = 'exists';
      statusLabel = 'Found';
    } else if (r.rateLimit) {
      statusClass = 'rate-limit';
      statusLabel = 'Rate Limit';
    } else if (r.error) {
      statusClass = 'error';
      statusLabel = 'Error';
    }

    let extras = '';
    if (r.emailrecovery) extras += r.emailrecovery;
    if (r.phoneNumber) extras += (extras ? ' / ' : '') + r.phoneNumber;

    tr.innerHTML = `
      <td class="email-cell">${escapeHtml(r.email)}</td>
      <td>${escapeHtml(r.domain)}</td>
      <td><span class="status-badge ${statusClass}">${statusLabel}</span></td>
      <td>${escapeHtml(extras)}</td>
    `;
    fragment.appendChild(tr);
  }
  els.resultsBody.appendChild(fragment);

  // Trim old rows from the top (single pass, no loop per-row)
  const excess = els.resultsBody.children.length - MAX_DOM_RESULT_ROWS;
  if (excess > 0) {
    for (let i = 0; i < excess; i++) {
      els.resultsBody.removeChild(els.resultsBody.firstChild);
    }
  }

  // Auto-scroll to bottom
  const wrapper = els.resultsBody.closest('.results-wrapper');
  if (wrapper) {
    wrapper.scrollTop = wrapper.scrollHeight;
  }
}

/**
 * Add a log line to the console. Trims old lines to MAX_DOM_LOG_LINES.
 */
function addLogLineDirect(level, message, time) {
  const line = document.createElement('div');
  line.className = `log-line ${level}`;
  line.innerHTML = `<span class="log-time">[${escapeHtml(time)}]</span>${escapeHtml(message)}`;
  els.logConsole.appendChild(line);

  // Trim old lines
  const excess = els.logConsole.children.length - MAX_DOM_LOG_LINES;
  if (excess > 0) {
    for (let i = 0; i < excess; i++) {
      els.logConsole.removeChild(els.logConsole.firstChild);
    }
  }

  els.logConsole.scrollTop = els.logConsole.scrollHeight;
}

function resetMonitoring() {
  els.resultsBody.innerHTML = '';
  if (els.resultsEmpty) els.resultsEmpty.style.display = '';
  els.logConsole.innerHTML = '';
  els.progressBar.style.width = '0%';
  els.progressPercent.textContent = '0%';
  els.progressText.innerHTML = '<strong>0</strong> / 0 emails processed';
  els.statTotal.textContent = '0';
  els.statSuccess.textContent = '0';
  els.statNotFound.textContent = '0';
  els.statRateLimit.textContent = '0';
  els.statErrors.textContent = '0';
  els.ratePerMinute.textContent = '0';
  els.ratePerHour.textContent = '0';
  els.ratePerDay.textContent = '0';
  els.ratePerWeek.textContent = '0';
}

function setJobState(state) {
  jobState = state;
  updateButtonStates();
  updateHeaderStatus();
  updateInputStates();
}

function updateButtonStates() {
  const isIdle = jobState === 'idle' || jobState === 'completed' || jobState === 'stopped';
  const isRunning = jobState === 'running';
  const isPaused = jobState === 'paused';

  els.btnStart.disabled = !isIdle;
  els.btnPause.disabled = !(isRunning || isPaused);
  els.btnStop.disabled = !(isRunning || isPaused);

  if (isPaused) {
    els.btnPause.innerHTML = '▶ Resume';
  } else {
    els.btnPause.innerHTML = '⏸ Pause';
  }

  const hasResults = els.resultsBody.children.length > 0;
  $$('.btn-export').forEach(btn => {
    btn.disabled = !hasResults;
  });
}

/**
 * Disable/enable input controls based on job state.
 */
function updateInputStates() {
  const isActive = jobState === 'running' || jobState === 'paused';

  els.emailInput.disabled = isActive;
  els.emailInput.style.opacity = isActive ? '0.6' : '1';

  els.threadSize.disabled = isActive;
  els.threadSize.style.opacity = isActive ? '0.6' : '1';



  $$('.domain-item input[type="checkbox"]').forEach(cb => {
    cb.disabled = isActive;
  });

  const btnSelectAll = $('#btn-select-all');
  const btnDeselectAll = $('#btn-deselect-all');
  if (btnSelectAll) btnSelectAll.disabled = isActive;
  if (btnDeselectAll) btnDeselectAll.disabled = isActive;

  $$('.proxy-tab').forEach(tab => {
    tab.disabled = isActive;
    tab.style.opacity = isActive ? '0.6' : '1';
    tab.style.pointerEvents = isActive ? 'none' : '';
  });

  ['#proxy-list-input', '#proxy-api-input', '#proxy-single-input'].forEach(sel => {
    const input = $(sel);
    if (input) {
      input.disabled = isActive;
      input.style.opacity = isActive ? '0.6' : '1';
    }
  });
}

function updateHeaderStatus() {
  els.statusDot.className = `status-dot ${jobState === 'completed' ? 'idle' : jobState}`;
  const labels = {
    idle: 'Idle',
    running: 'Running',
    paused: 'Paused',
    stopped: 'Stopped',
    completed: 'Completed',
  };
  els.statusText.textContent = labels[jobState] || 'Idle';
}

// ---------- Logging ----------
function addLog(level, message) {
  const now = new Date().toLocaleTimeString('en-US', { hour12: false });
  addLogLineDirect(level, message, now);
}

// ---------- Export ----------
async function exportResults(type, format) {
  try {
    const url = `${API.export}/${type}/${format}`;
    const res = await fetch(url);
    if (!res.ok) {
      addLog('error', `Export failed: ${res.statusText}`);
      return;
    }
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `mahoraga_${type}_results.${format}`;
    a.click();
    URL.revokeObjectURL(a.href);
    addLog('success', `Exported ${type} results as ${format.toUpperCase()}`);
  } catch (e) {
    addLog('error', `Export failed: ${e.message}`);
  }
}

// ---------- Helpers ----------
function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
