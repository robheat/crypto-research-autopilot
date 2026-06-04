/* Crypto Research Autopilot — app.js */

// ── State ──────────────────────────────────────────────────────────────────
let currentVaultFile = null;
let vaultPreviewMode = false;

// ── Utilities ──────────────────────────────────────────────────────────────

function toast(msg, type = 'info') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.style.background = type === 'error' ? '#450a0a' : type === 'success' ? '#052e16' : '#1e293b';
  el.style.color = type === 'error' ? '#fca5a5' : type === 'success' ? '#6ee7b7' : '#e2e8f0';
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 3500);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

function renderMarkdown(md) {
  return marked.parse(md || '', { breaks: true });
}

// ── Tab switching ──────────────────────────────────────────────────────────

const TABS = ['brief', 'vault', 'watchlist', 'research', 'settings'];

function switchTab(name) {
  TABS.forEach(t => {
    document.getElementById(`tab-${t}`).classList.toggle('hidden', t !== name);
  });
  document.querySelectorAll('.tab-btn').forEach((btn, i) => {
    const active = TABS[i] === name;
    btn.classList.toggle('active', active);
    btn.classList.toggle('text-gray-400', !active);
    btn.classList.toggle('hover:text-white', !active);
  });
  if (name === 'brief') loadBriefHistory();
  if (name === 'vault') loadVaultFiles();
  if (name === 'watchlist') loadWatchlist();
  if (name === 'settings') loadSettings();
}

// ── Brief Tab ─────────────────────────────────────────────────────────────

async function loadBriefHistory() {
  try {
    const history = await api('/api/brief/history');
    const container = document.getElementById('brief-history');
    if (!history.length) {
      container.innerHTML = '<p class="text-gray-600 text-xs">No briefs yet.</p>';
      return;
    }
    container.innerHTML = history.map(f => `
      <button onclick="loadBriefFile('${f.path}')"
        class="w-full text-left px-2 py-1.5 rounded text-xs text-gray-400 hover:bg-gray-800 hover:text-white truncate">
        ${f.name.replace('brief-', '')}
      </button>
    `).join('');

    // Auto-load latest
    if (history.length) loadBriefFile(history[0].path);
  } catch (e) {
    toast('Failed to load brief history: ' + e.message, 'error');
  }
}

async function loadBriefFile(path) {
  try {
    const data = await api(`/api/brief/file?path=${encodeURIComponent(path)}`);
    document.getElementById('brief-content').innerHTML = renderMarkdown(data.content);
  } catch (e) {
    toast('Failed to load brief: ' + e.message, 'error');
  }
}

async function generateBrief() {
  const btn = document.getElementById('generate-btn');
  const status = document.getElementById('brief-status');
  const webSearch = document.getElementById('web-search-toggle').checked;

  btn.disabled = true;
  btn.innerHTML = '<div class="spinner" style="width:1rem;height:1rem;border-width:2px;"></div><span>Generating…</span>';
  status.classList.remove('hidden');

  try {
    const result = await api('/api/brief/generate', {
      method: 'POST',
      body: JSON.stringify({ web_search: webSearch }),
    });
    document.getElementById('brief-content').innerHTML = renderMarkdown(result.content);
    toast('Brief generated and saved to vault!', 'success');
    loadBriefHistory();
  } catch (e) {
    toast('Error: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span>Generate Now</span>';
    status.classList.add('hidden');
  }
}

// ── Vault Tab ─────────────────────────────────────────────────────────────

async function loadVaultFiles() {
  const folder = document.getElementById('vault-folder-filter').value;
  const container = document.getElementById('vault-file-list');
  try {
    const files = await api(`/api/vault/files?folder=${encodeURIComponent(folder)}`);
    if (!files.length) {
      container.innerHTML = '<p class="text-gray-600 text-xs px-2">No files found.</p>';
      return;
    }
    container.innerHTML = files.map(f => `
      <button onclick="openVaultFile('${f.path}')"
        class="w-full text-left px-2 py-1.5 rounded text-xs hover:bg-gray-800 ${currentVaultFile === f.path ? 'bg-gray-800 text-white' : 'text-gray-400'}">
        <div class="font-medium truncate">${f.name}</div>
        <div class="text-gray-600 truncate text-[10px]">${f.folder}</div>
      </button>
    `).join('');
  } catch (e) {
    toast('Failed to load files: ' + e.message, 'error');
  }
}

async function openVaultFile(path) {
  currentVaultFile = path;
  try {
    const data = await api(`/api/vault/file?path=${encodeURIComponent(path)}`);
    document.getElementById('vault-editor-title').textContent = path;
    document.getElementById('vault-editor').value = data.content;
    document.getElementById('vault-editor-wrap').classList.remove('hidden');
    document.getElementById('vault-editor-placeholder').classList.add('hidden');
    // Reset to edit mode
    vaultPreviewMode = false;
    document.getElementById('vault-editor').classList.remove('hidden');
    document.getElementById('vault-preview').classList.add('hidden');
    document.getElementById('vault-preview-btn').textContent = 'Preview';
    loadVaultFiles();
  } catch (e) {
    toast('Failed to open file: ' + e.message, 'error');
  }
}

function toggleVaultPreview() {
  vaultPreviewMode = !vaultPreviewMode;
  const editor = document.getElementById('vault-editor');
  const preview = document.getElementById('vault-preview');
  const btn = document.getElementById('vault-preview-btn');
  if (vaultPreviewMode) {
    preview.innerHTML = renderMarkdown(editor.value);
    editor.classList.add('hidden');
    preview.classList.remove('hidden');
    btn.textContent = 'Edit';
  } else {
    editor.classList.remove('hidden');
    preview.classList.add('hidden');
    btn.textContent = 'Preview';
  }
}

async function saveVaultFile() {
  if (!currentVaultFile) return;
  const content = document.getElementById('vault-editor').value;
  try {
    await api('/api/vault/file', {
      method: 'POST',
      body: JSON.stringify({ path: currentVaultFile, content }),
    });
    toast('Saved!', 'success');
  } catch (e) {
    toast('Save failed: ' + e.message, 'error');
  }
}

async function deleteVaultFile() {
  if (!currentVaultFile) return;
  if (!confirm(`Delete ${currentVaultFile}?`)) return;
  try {
    await api(`/api/vault/file?path=${encodeURIComponent(currentVaultFile)}`, { method: 'DELETE' });
    currentVaultFile = null;
    document.getElementById('vault-editor-wrap').classList.add('hidden');
    document.getElementById('vault-editor-placeholder').classList.remove('hidden');
    toast('Deleted.', 'success');
    loadVaultFiles();
  } catch (e) {
    toast('Delete failed: ' + e.message, 'error');
  }
}

function openNewFileModal() {
  document.getElementById('new-file-modal').classList.remove('hidden');
  document.getElementById('new-file-name').focus();
}

function closeNewFileModal() {
  document.getElementById('new-file-modal').classList.add('hidden');
}

async function createNewFile() {
  const folder = document.getElementById('new-file-folder').value;
  let name = document.getElementById('new-file-name').value.trim();
  if (!name) { toast('Enter a filename', 'error'); return; }
  if (!name.endsWith('.md')) name += '.md';
  const path = `${folder}/${name}`;
  const today = new Date().toISOString().split('T')[0];
  try {
    await api('/api/vault/file', {
      method: 'POST',
      body: JSON.stringify({ path, content: `# ${name.replace('.md','')}\n\n*Created: ${today}*\n\n` }),
    });
    closeNewFileModal();
    document.getElementById('new-file-name').value = '';
    toast('File created!', 'success');
    openVaultFile(path);
  } catch (e) {
    toast('Error: ' + e.message, 'error');
  }
}

// ── Watchlist Tab ─────────────────────────────────────────────────────────

async function loadWatchlist() {
  try {
    const tokens = await api('/api/watchlist');
    const tbody = document.getElementById('watchlist-tbody');
    const empty = document.getElementById('watchlist-empty');
    if (!tokens.length) {
      tbody.innerHTML = '';
      empty.classList.remove('hidden');
      return;
    }
    empty.classList.add('hidden');
    tbody.innerHTML = tokens.map(t => `
      <tr class="hover:bg-gray-800/50">
        <td class="px-4 py-3 font-mono font-semibold text-indigo-400">${escapeHtml(t.symbol?.toUpperCase() || '')}</td>
        <td class="px-4 py-3 text-white">${escapeHtml(t.name || '')}</td>
        <td class="px-4 py-3 text-gray-500 text-xs font-mono">${escapeHtml(t.coingecko_id || '—')}</td>
        <td class="px-4 py-3 text-gray-400 text-xs max-w-xs truncate">${escapeHtml(t.entry_rationale || '—')}</td>
        <td class="px-4 py-3 text-right">
          <button onclick="removeToken('${escapeHtml(t.symbol)}')" class="text-xs text-red-400 hover:text-red-300">Remove</button>
        </td>
      </tr>
    `).join('');
  } catch (e) {
    toast('Failed to load watchlist: ' + e.message, 'error');
  }
}

async function addToWatchlist() {
  const symbol = document.getElementById('wl-symbol').value.trim();
  const name = document.getElementById('wl-name').value.trim();
  if (!symbol || !name) { toast('Symbol and name are required', 'error'); return; }
  try {
    await api('/api/watchlist', {
      method: 'POST',
      body: JSON.stringify({
        symbol,
        name,
        coingecko_id: document.getElementById('wl-cgid').value.trim(),
        entry_rationale: document.getElementById('wl-rationale').value.trim(),
        notes: document.getElementById('wl-notes').value.trim(),
      }),
    });
    ['wl-symbol','wl-name','wl-cgid','wl-rationale','wl-notes'].forEach(id => document.getElementById(id).value = '');
    toast(`${symbol.toUpperCase()} added to watchlist`, 'success');
    loadWatchlist();
  } catch (e) {
    toast('Error: ' + e.message, 'error');
  }
}

async function removeToken(symbol) {
  if (!confirm(`Remove ${symbol} from watchlist?`)) return;
  try {
    await api(`/api/watchlist/${encodeURIComponent(symbol)}`, { method: 'DELETE' });
    toast(`${symbol} removed`, 'success');
    loadWatchlist();
  } catch (e) {
    toast('Error: ' + e.message, 'error');
  }
}

// ── Research Tab ──────────────────────────────────────────────────────────

async function generateResearch() {
  const name = document.getElementById('res-name').value.trim();
  const symbol = document.getElementById('res-symbol').value.trim();
  if (!name || !symbol) { toast('Token name and symbol are required', 'error'); return; }

  const btn = document.getElementById('res-btn');
  const status = document.getElementById('res-status');
  const result = document.getElementById('res-result');
  const placeholder = document.getElementById('res-placeholder');

  btn.disabled = true;
  btn.innerHTML = '<div class="spinner" style="width:1rem;height:1rem;border-width:2px;"></div><span>Researching…</span>';
  status.classList.remove('hidden');
  result.classList.add('hidden');
  placeholder.classList.add('hidden');

  try {
    const data = await api('/api/research/token', {
      method: 'POST',
      body: JSON.stringify({
        token_name: name,
        symbol,
        coingecko_id: document.getElementById('res-cgid').value.trim(),
        custom_notes: document.getElementById('res-notes').value.trim(),
      }),
    });
    result.innerHTML = renderMarkdown(data.content);
    result.classList.remove('hidden');
    toast(`Research note saved to ${data.path}`, 'success');
  } catch (e) {
    placeholder.classList.remove('hidden');
    toast('Research failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span>Generate Research Note</span>';
    status.classList.add('hidden');
  }
}

// ── Settings Tab ──────────────────────────────────────────────────────────

async function loadSettings() {
  try {
    const s = await api('/api/settings');
    document.getElementById('s-venice-status').innerHTML = s.venice_api_key_set
      ? '<span class="badge-green">✓ Set</span>'
      : '<span class="badge-red">Not set</span>';
    document.getElementById('s-model').value = s.venice_model || '';
    document.getElementById('s-cron').value = s.brief_schedule_cron || '0 6 * * *';    document.getElementById('s-github-status').innerHTML = s.github_token_set
      ? '<span class="badge-green">\u2713 Set</span>'
      : '<span class="badge-gray">Not set</span>';
    document.getElementById('s-github-repo').value = s.github_repo || 'robheat/cryptocatalyst-news';    // Don't pre-fill password fields for security
  } catch (e) {
    toast('Failed to load settings', 'error');
  }
}

async function saveSettings() {
  const body = {};
  const veniceKey = document.getElementById('s-venice-key').value.trim();
  const cmcKey = document.getElementById('s-cmc-key').value.trim();
  const lcKey = document.getElementById('s-lc-key').value.trim();
  const model = document.getElementById('s-model').value.trim();
  const cron = document.getElementById('s-cron').value.trim();
  const githubToken = document.getElementById('s-github-token').value.trim();
  const githubRepo = document.getElementById('s-github-repo').value.trim();

  if (veniceKey) body.venice_api_key = veniceKey;
  if (cmcKey) body.cmc_api_key = cmcKey;
  if (lcKey) body.lunarcrush_api_key = lcKey;
  if (model) body.venice_model = model;
  if (cron) body.brief_schedule_cron = cron;
  if (githubToken) body.github_token = githubToken;
  if (githubRepo) body.github_repo = githubRepo;

  if (!Object.keys(body).length) { toast('Nothing to save', 'error'); return; }

  try {
    const res = await api('/api/settings', { method: 'POST', body: JSON.stringify(body) });
    toast('Settings saved! Updated: ' + res.updated.join(', '), 'success');
    // Clear password fields
    document.getElementById('s-venice-key').value = '';
    document.getElementById('s-cmc-key').value = '';
    document.getElementById('s-lc-key').value = '';
    document.getElementById('s-github-token').value = '';
    loadSettings();
  } catch (e) {
    toast('Save failed: ' + e.message, 'error');
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Init ──────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  loadBriefHistory();
  // Show status
  document.getElementById('status-bar').textContent = `Vault: vault/ | ${new Date().toLocaleString()}`;
});
