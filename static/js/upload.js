/**
 * upload.js — handles Drive Importer form (new /api/upload/{name} endpoint),
 * background jobs table, and cookies health banner on dashboard.
 */

// ── Drive Importer Form ───────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('drive-import-form');
  if (form) form.addEventListener('submit', handleDriveImport);

  // Load jobs when the jobs tab is clicked
  document.querySelectorAll('[data-tab="jobs-tab"]').forEach(btn => {
    btn.addEventListener('click', () => loadJobs());
  });

  setupJobModalListeners();

  // Initial cookies health check
  checkCookiesHealth();
});

async function handleDriveImport(e) {
  e.preventDefault();

  const rawId = document.getElementById('drive_file_id').value.trim();

  // Extract file ID from full Drive URL if pasted
  const driveId = extractDriveId(rawId);
  if (!driveId) {
    UI.toast('Invalid Drive File ID or URL', 'error');
    return;
  }

  const btn = e.target.querySelector('button[type="submit"]');
  btn.disabled = true;
  btn.textContent = 'Importing…';

  try {
    const token = API.getToken();
    const resp = await fetch('/api/upload', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({ drive_id: driveId }),
    });

    const data = await resp.json();

    if (!resp.ok) {
      UI.toast(data.detail || 'Import failed', 'error');
      return;
    }

    // Show result card
    const resultCard = document.getElementById('drive-import-result');
    resultCard.hidden = false;

    const downloadPageUrl = `/download/${data.token}`;
    document.getElementById('drive-res-status-text').textContent =
      data.status === 'already_exists' ? 'Already Exists — Token Retrieved' : 'Import Queued!';
    document.getElementById('drive-res-token').textContent = data.token;
    if (document.getElementById('drive-res-filename')) {
      document.getElementById('drive-res-filename').textContent = data.filename || '—';
    }
    if (document.getElementById('drive-res-filesize')) {
      const sz = data.file_size
        ? (data.file_size >= 1024 * 1024 * 1024
          ? (data.file_size / (1024 * 1024 * 1024)).toFixed(2) + ' GB'
          : (data.file_size / (1024 * 1024)).toFixed(1) + ' MB')
        : '—';
      document.getElementById('drive-res-filesize').textContent = sz;
    }

    const dlLink = document.getElementById('drive-res-download-link');
    dlLink.href = downloadPageUrl;
    dlLink.textContent = window.location.origin + downloadPageUrl;

    const openBtn = document.getElementById('drive-res-open-btn');
    openBtn.href = downloadPageUrl;

    const copyBtn = document.getElementById('drive-res-copy-btn');
    copyBtn.onclick = () => {
      navigator.clipboard.writeText(window.location.origin + downloadPageUrl)
        .then(() => UI.toast('Download link copied!', 'success'));
    };

    UI.toast(
      data.status === 'already_exists' ? 'Token retrieved (already imported)' : 'Import started — processing in background',
      'success',
    );

  } catch (err) {
    UI.toast('Network error: ' + err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Import &amp; Get Download Link <span data-icon="arrow-right" data-size="16"></span>';
    if (typeof window.renderIcons === 'function') window.renderIcons();
  }
}

function extractDriveId(raw) {
  if (!raw) return null;
  // Full URL: https://drive.google.com/file/d/{ID}/view
  const m = raw.match(/\/d\/([a-zA-Z0-9_-]{10,})/);
  if (m) return m[1];
  // Plain ID: alphanumeric 20-44 chars
  if (/^[a-zA-Z0-9_-]{10,}$/.test(raw)) return raw;
  return null;
}


// ── Background Jobs Table ─────────────────────────────────────────────────────

// ── Background Jobs Table ─────────────────────────────────────────────────────

async function loadJobs() {
  const tbody = document.getElementById('jobs-table-body');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted)">Loading…</td></tr>';

  try {
    const token = API.getToken();
    const resp = await fetch('/api/jobs?limit=100', {
      headers: { 'Authorization': `Bearer ${token}` },
    });
    if (!resp.ok) throw new Error(resp.statusText);
    const jobs = await resp.json();

    if (!jobs.length) {
      tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted)">No jobs yet.</td></tr>';
      return;
    }

    tbody.innerHTML = jobs.map(j => {
      let displayStatus = (j.status || 'unknown').toUpperCase();
      let statusColor = '#94a3b8';

      if (j.status === 'running') {
        displayStatus = 'RUNNING';
        statusColor = '#60a5fa';
      } else if (j.status === 'failed') {
        displayStatus = 'FAILED';
        statusColor = '#f87171';
      } else if (j.status === 'done') {
        displayStatus = 'DONE';
        statusColor = '#34d399';
      } else if (j.status === 'pending') {
        if (j.run_every_sec) {
          displayStatus = 'SCHEDULED';
          statusColor = '#34d399';
        } else {
          displayStatus = 'QUEUED';
          statusColor = '#fbbf24';
        }
      }

      const intervalText = j.run_every_sec ? formatInterval(j.run_every_sec) : '—';
      let resultText = '—';
      if (j.result) {
        try {
          const r = JSON.parse(j.result);
          resultText = Object.entries(r).map(([k, v]) => {
            if (typeof v === 'object' && v !== null) {
              if (k === 'sessions') {
                const count = Object.keys(v).length;
                const valids = Object.values(v).filter(x => x && x.valid).length;
                return `sessions: ${valids}/${count} valid`;
              }
              return `${k}: ${JSON.stringify(v)}`;
            }
            if (k === 'transcoding_wait') return `⏳ Google transcoding: ${v} item`;
            if (k === 'promoting_wait') return `⏳ Promote backoff: ${v} item`;
            return `${k}: ${v}`;
          }).join(', ');
        } catch { resultText = j.result.slice(0, 60); }
      }
      return `<tr>
        <td><code style="font-size:.75rem">${j.id}</code></td>
        <td><code style="font-size:.8rem">${j.job_type}</code></td>
        <td><span style="color:${statusColor};font-weight:600;font-size:.82rem">${displayStatus}</span></td>
        <td style="font-size:.78rem;color:var(--text-muted)">${j.last_run_at ? fmtDate(j.last_run_at) : '—'}</td>
        <td style="font-size:.78rem;color:var(--text-muted)">${j.next_run_at ? fmtDate(j.next_run_at) : '—'}</td>
        <td style="font-size:.78rem;color:var(--text-muted)">${intervalText}</td>
        <td style="font-size:.75rem;color:var(--text-muted);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${resultText}">${resultText}</td>
        <td style="font-size:.78rem;white-space:nowrap">
          <div style="display:flex;gap:0.35rem;align-items:center;">
            <button class="btn btn-secondary btn-sm" onclick="runJobNow(${j.id})" title="Trigger immediate execution" style="padding:0.2rem 0.5rem;font-size:0.75rem;">
              <span data-icon="play" data-size="12"></span> Run
            </button>
            <button class="btn btn-secondary btn-sm" onclick="openEditJobModal(${j.id}, '${j.job_type}', ${j.run_every_sec || 0})" title="Edit interval / schedule" style="padding:0.2rem 0.5rem;font-size:0.75rem;">
              <span data-icon="edit-2" data-size="12"></span> Edit
            </button>
          </div>
        </td>
      </tr>`;
    }).join('');

    if (typeof window.renderIcons === 'function') window.renderIcons();

  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" style="color:var(--accent-red)">Error: ${err.message}</td></tr>`;
  }
}

async function runJobNow(jobId) {
  try {
    const token = API.getToken();
    const resp = await fetch(`/api/jobs/${jobId}/run-now`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || resp.statusText);
    UI.toast(`Job #${jobId} triggered — will run within seconds`, 'success');
    await loadJobs();
  } catch (err) {
    UI.toast('Failed to trigger job: ' + err.message, 'error');
  }
}

const DEFAULT_JOB_INTERVALS = {
  pipeline_sweep: 20,
  cookies_check: 300,
  cache_cleanup: 1800,
  daily_cleanup: 86400,
};

function openEditJobModal(jobId, jobType, currentInterval) {
  const modal = document.getElementById('edit-job-modal');
  if (!modal) {
    console.error('edit-job-modal not found');
    return;
  }
  modal.dataset.jobType = jobType;
  const idInput = document.getElementById('edit-job-id');
  const typeDisplay = document.getElementById('edit-job-type-display');
  const intervalInput = document.getElementById('edit-job-interval-sec');
  const presetSelect = document.getElementById('edit-job-interval-preset');
  const triggerNowCb = document.getElementById('edit-job-trigger-now');

  if (idInput) idInput.value = jobId;
  if (typeDisplay) typeDisplay.textContent = jobType;

  const defaultSec = DEFAULT_JOB_INTERVALS[jobType] || 300;
  const sec = currentInterval || defaultSec;
  if (intervalInput) intervalInput.value = sec;

  if (presetSelect) {
    const matched = Array.from(presetSelect.options).some(opt => opt.value === String(sec));
    presetSelect.value = matched ? String(sec) : 'custom';
  }
  if (triggerNowCb) triggerNowCb.checked = false;

  if (typeof UI !== 'undefined' && UI.openModal) {
    UI.openModal(modal);
  } else {
    modal.classList.add('open');
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
  }

  if (typeof window.hydrateIcons === 'function') window.hydrateIcons(modal);
}

function closeEditJobModal() {
  const modal = document.getElementById('edit-job-modal');
  if (!modal) return;
  if (typeof UI !== 'undefined' && UI.closeModal) {
    UI.closeModal(modal);
  } else {
    modal.classList.remove('open');
    modal.classList.remove('active');
    document.body.style.overflow = '';
  }
}

window.openEditJobModal = openEditJobModal;
window.closeEditJobModal = closeEditJobModal;

function setupJobModalListeners() {
  const modal = document.getElementById('edit-job-modal');
  if (!modal) return;

  const closeBtn = document.getElementById('close-edit-job-modal');
  const cancelBtn = document.getElementById('cancel-edit-job-btn');
  const resetBtn = document.getElementById('reset-edit-job-btn');
  const form = document.getElementById('edit-job-form');
  const presetSelect = document.getElementById('edit-job-interval-preset');
  const intervalInput = document.getElementById('edit-job-interval-sec');

  if (closeBtn) closeBtn.addEventListener('click', closeEditJobModal);
  if (cancelBtn) cancelBtn.addEventListener('click', closeEditJobModal);

  if (resetBtn && intervalInput && presetSelect) {
    resetBtn.addEventListener('click', () => {
      const jobType = modal.dataset.jobType || 'pipeline_sweep';
      const defaultSec = DEFAULT_JOB_INTERVALS[jobType] || 300;
      intervalInput.value = defaultSec;
      const matched = Array.from(presetSelect.options).some(opt => opt.value === String(defaultSec));
      presetSelect.value = matched ? String(defaultSec) : 'custom';
      if (typeof UI !== 'undefined' && UI.toast) {
        UI.toast(`Reset to default: ${defaultSec}s (${formatInterval(defaultSec)})`, 'info');
      }
    });
  }

  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeEditJobModal();
  });

  if (presetSelect && intervalInput) {
    presetSelect.addEventListener('change', () => {
      if (presetSelect.value !== 'custom') {
        intervalInput.value = presetSelect.value;
      }
    });

    intervalInput.addEventListener('input', () => {
      const val = intervalInput.value;
      const matched = Array.from(presetSelect.options).some(opt => opt.value === val);
      presetSelect.value = matched ? val : 'custom';
    });
  }

  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const jobId = document.getElementById('edit-job-id').value;
      const intervalSec = parseInt(intervalInput.value, 10);
      const triggerNow = document.getElementById('edit-job-trigger-now').checked;

      if (isNaN(intervalSec) || intervalSec < 5) {
        UI.toast('Interval must be at least 5 seconds', 'error');
        return;
      }

      try {
        const token = API.getToken();
        const resp = await fetch(`/api/jobs/${jobId}`, {
          method: 'PATCH',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
          },
          body: JSON.stringify({
            run_every_sec: intervalSec,
            run_now: triggerNow,
            trigger_now: triggerNow,
          }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || resp.statusText);

        UI.toast(`Job #${jobId} updated — runs every ${formatInterval(intervalSec)}`, 'success');
        closeEditJobModal();
        await loadJobs();
      } catch (err) {
        UI.toast('Failed to update job: ' + err.message, 'error');
      }
    });
  }
}

function formatInterval(sec) {
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  return `${Math.round(sec / 3600)}h`;
}

function fmtDate(iso) {
  try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }); }
  catch { return iso; }
}


// ── Cookies Health Banner ─────────────────────────────────────────────────────

async function checkCookiesHealth() {
  const banner = document.getElementById('cookies-health-banner');
  const titleEl = document.getElementById('cookies-health-title');
  const detailEl = document.getElementById('cookies-health-detail');
  const iconEl = document.getElementById('cookies-health-icon');
  if (!banner) return;

  try {
    const token = API.getToken();
    const resp = await fetch('/api/web/sessions', {
      headers: { 'Authorization': `Bearer ${token}` },
    });
    if (!resp.ok) throw new Error('Could not load sessions');
    const sessions = await resp.json();

    const activeSessions = sessions.filter(s => s.is_active);

    if (!activeSessions.length) {
      showBanner(banner, titleEl, detailEl, iconEl,
        'No Active Cookies',
        'No active web sessions found. Import will be unavailable until you add a cookie session.',
        '#f87171', 'alert-triangle');
      return;
    }

    // Check each active session
    const results = await Promise.allSettled(
      activeSessions.map(async s => {
        const r = await fetch(`/api/web/sessions/${s.session_id}/check`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${token}` },
        });
        const d = await r.json();
        return { session_id: s.session_id, name: s.name, ...d };
      })
    );

    const valid = results.filter(r => r.status === 'fulfilled' && r.value.valid);
    const invalid = results.filter(r => r.status === 'fulfilled' && !r.value.valid);

    if (invalid.length > 0 && valid.length === 0) {
      showBanner(banner, titleEl, detailEl, iconEl,
        'All Cookies Expired',
        `${invalid.length} session(s) expired/invalid. Import is blocked. Please update your cookies.`,
        '#f87171', 'alert-circle');
    } else if (invalid.length > 0) {
      showBanner(banner, titleEl, detailEl, iconEl,
        `${invalid.length} Session(s) Expired`,
        `${valid.length} valid, ${invalid.length} expired. Import will use valid sessions.`,
        '#fbbf24', 'alert-triangle');
    } else {
      showBanner(banner, titleEl, detailEl, iconEl,
        `All Cookies Valid (${valid.length} session${valid.length !== 1 ? 's' : ''})`,
        `Accounts: ${valid.map(r => r.value.account || r.value.name).join(', ')}`,
        '#34d399', 'shield-check');
    }

  } catch (err) {
    // Not logged in yet or error — hide banner silently
    banner.hidden = true;
  }
}

function showBanner(banner, titleEl, detailEl, iconEl, title, detail, color, icon) {
  banner.hidden = false;
  banner.style.borderLeftColor = color;
  titleEl.textContent = title;
  detailEl.textContent = detail;
  iconEl.setAttribute('data-icon', icon);
  iconEl.style.color = color;
  if (typeof window.renderIcons === 'function') window.renderIcons();
}
