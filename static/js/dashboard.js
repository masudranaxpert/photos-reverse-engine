/**
 * Dashboard & Main Application Logic
 * Uses: icons.js (icon), ui.js (UI), api.js (API, Toast, copyToClipboard)
 */

let currentPage = 1;
let currentSearch = "";
let currentSource = "all";

document.addEventListener("DOMContentLoaded", () => {
  // If not on login page, enforce authentication
  if (!window.location.pathname.includes("/login")) {
    if (!API.isAuthenticated()) {
      window.location.href = "/login";
      return;
    }

    // Set user header badge
    const userDisplay = document.getElementById("current-user-display");
    if (userDisplay) {
      userDisplay.textContent = API.getUsername();
    }

    // Initialize Dashboard
    initTabs();
    loadDashboardStats();
    loadSystemNotices();
    loadMediaFiles(1);

    // Filter & Search Listeners
    setupMediaFilters();

    // Forms Setup
    setupDriveImportForm();
    setupShareImportForm();
    setupSessionManager();
    setupMobileManager();
    setupApiKeyManager();
    setupAdminManager();
    setupDriveApiKeySetting();
    setupConcurrencySetting();
    setupMediaErrorModal();
    setupResetMediaModal();
  }
});

/**
 * Tab Navigation
 */
function initTabs() {
  const tabButtons = document.querySelectorAll(".tab-btn");
  const tabPanels = document.querySelectorAll(".tab-content");

  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetId = btn.getAttribute("data-tab");

      tabButtons.forEach((b) => b.classList.remove("active"));
      tabPanels.forEach((p) => p.classList.remove("active"));

      btn.classList.add("active");
      const targetPanel = document.getElementById(targetId);
      if (targetPanel) {
        targetPanel.classList.add("active");
      }

      // Lazy load tab contents
      if (targetId === "media-tab") loadMediaFiles(currentPage);
      if (targetId === "web-tab") loadWebSessions();
      if (targetId === "mobile-tab") loadMobileAccounts();
      if (targetId === "keys-tab") loadApiKeys();
      if (targetId === "admin-tab") {
        loadAdmins();
        loadDriveApiKeySetting();
        loadConcurrencySetting();
      }
      if (targetId === "jobs-tab") {
        if (typeof loadJobs === "function") loadJobs();
      }
    });
  });
}

/**
 * Top Metrics Loader
 */
async function loadDashboardStats() {
  try {
    const stats = await API.request("/api/media/stats");
    const totalEl = document.getElementById("stat-total-media");
    if (totalEl) totalEl.textContent = stats.total_media || 0;
    const webEl = document.getElementById("stat-web-sessions");
    if (webEl) webEl.textContent = stats.active_web_sessions || 0;
    const mobEl = document.getElementById("stat-mobile-accounts");
    if (mobEl) mobEl.textContent = stats.active_mobile_accounts || 0;
    const cachedEl = document.getElementById("stat-cached-links");
    if (cachedEl) cachedEl.textContent = stats.cached_download_urls || 0;
    const streamCacheEl = document.getElementById("stat-stream-cache");
    if (streamCacheEl) streamCacheEl.textContent = stats.cached_stream_urls || 0;

    // Update Media Explorer pipeline stage counters
    const stageAllEl = document.getElementById("stage-count-all");
    if (stageAllEl) stageAllEl.textContent = stats.total_media || 0;
    const stageTempEl = document.getElementById("stage-count-temp");
    if (stageTempEl) stageTempEl.textContent = stats.temp_count || 0;
    const stagePermEl = document.getElementById("stage-count-permanent");
    if (stagePermEl) stagePermEl.textContent = stats.permanent_count || 0;

    loadSystemNotices();
  } catch (err) {
    console.warn("Failed to load dashboard stats", err);
  }
}

/**
 * System Audit Strip — one-line summary on the dashboard.
 * The full, paginated log lives on the dedicated /audit page.
 */
const AUDIT_SEVERITY = { critical: 4, error: 3, warning: 2, info: 1 };

async function loadSystemNotices() {
  const strip = document.getElementById("audit-strip");
  const textEl = document.getElementById("audit-strip-text");
  const iconEl = document.getElementById("audit-strip-icon");
  if (!strip || !textEl) return;

  try {
    const res = await API.request("/api/notices");
    const notices = res.notices || [];

    if (notices.length === 0) {
      strip.hidden = true;
      return;
    }

    const topLevel = notices.reduce(
      (worst, n) => ((AUDIT_SEVERITY[n.level] || 0) > (AUDIT_SEVERITY[worst] || 0) ? n.level : worst),
      "info"
    ) || "warning";
    const latest = notices[0] || {};
    const when = UI.formatDate(latest.updated_at || latest.created_at) || "-";
    const title = UI.escapeHtml(latest.title || "System alert");

    // Populate fully BEFORE revealing — the strip must never render blank.
    textEl.innerHTML =
      `<strong>${notices.length} active alert${notices.length > 1 ? "s" : ""}</strong>` +
      ` — latest: ${title} · ${UI.escapeHtml(when)}`;
    strip.className = `audit-strip level-${topLevel}`;
    if (iconEl) iconEl.className = `audit-strip-icon level-${topLevel}`;
    strip.hidden = false;
  } catch (err) {
    console.warn("Failed to load system notices", err);
    if (strip) strip.hidden = true;
  }
}

async function confirmResetAccount() {
  if (!confirm("Are you sure you want to permanently wipe your Google Photos library and empty trash to recover storage quota? All items currently in Google Photos will be removed.")) {
    return;
  }
  try {
    Toast.show("Wiping Google Photos library and emptying trash...", "info");
    const res = await API.request("/api/web/reset-account", {
      method: "POST",
      body: { confirm: true },
    });
    Toast.show(res.message || "Account reset complete! Storage quota freed.", "success");
    loadDashboardStats();
    loadSystemNotices();
    loadMediaFiles(1);
  } catch (err) {
    Toast.show(`Account reset failed: ${err.message}`, "error");
  }
}

/**
 * Media Files Explorer: 3-Stage Pipeline (All Drive Files, Temporary Queue, Permanent Library)
 */
function setupMediaFilters() {
  const searchInput = document.getElementById("media-search-input");

  let searchTimeout;
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => {
        currentSearch = e.target.value.trim();
        loadMediaFiles(1);
      }, 350);
    });
  }
}

function setMediaStage(stage) {
  currentSource = stage;
  const pills = {
    all: document.getElementById("stage-btn-all"),
    temp: document.getElementById("stage-btn-temp"),
    permanent: document.getElementById("stage-btn-permanent"),
  };

  Object.keys(pills).forEach((k) => {
    if (pills[k]) pills[k].classList.toggle("active", k === stage);
  });

  const btnClearTemp = document.getElementById("btn-clear-temp");
  const btnClearPerm = document.getElementById("btn-clear-permanent");
  const btnClearErrors = document.getElementById("btn-clear-errors");
  const btnRequeueErrors = document.getElementById("btn-requeue-errors");
  if (btnClearTemp) btnClearTemp.style.display = (stage === "temp") ? "inline-flex" : "none";
  if (btnClearPerm) btnClearPerm.style.display = (stage === "permanent") ? "inline-flex" : "none";
  if (btnClearErrors) btnClearErrors.style.display = (stage === "all") ? "inline-flex" : "none";
  if (btnRequeueErrors) btnRequeueErrors.style.display = (stage === "all") ? "inline-flex" : "none";

  loadMediaFiles(1);
}

function stageBadge(stage) {
  if (stage === "permanent") return UI.badge("Permanent (Mobile)", "emerald");
  if (stage === "temp") return UI.badge("Temporary Queue", "amber");
  if (stage === "queued") return UI.badge("Queued Import", "indigo");
  if (stage === "not_found") return UI.badge("Drive Missing", "rose");
  if (stage === "unsupported") return UI.badge("Format Unsupported", "rose");
  if (stage === "error") return UI.badge("Drive Error", "rose");
  if (stage === "ok") return UI.badge("Drive Ref", "sky");
  return UI.badge(stage, "neutral");
}

function renderMediaTableHeader(stage) {
  const thead = document.getElementById("media-table-head");
  if (!thead) return;

  if (stage === "permanent") {
    thead.innerHTML = `
      <tr>
        <th>File / Title</th>
        <th>Media Key</th>
        <th>Account</th>
        <th>Download Link</th>
        <th>Visitors</th>
        <th>Promoted</th>
        <th>Actions</th>
      </tr>`;
  } else if (stage === "temp") {
    thead.innerHTML = `
      <tr>
        <th>File / Title</th>
        <th>Media Key</th>
        <th>Dedup Key</th>
        <th>Status</th>
        <th>Visitors</th>
        <th>Share Link</th>
        <th>Imported</th>
        <th>Actions</th>
      </tr>`;
  } else {
    thead.innerHTML = `
      <tr>
        <th>File / Title</th>
        <th>Drive ID</th>
        <th>Stage</th>
        <th>Download Link</th>
        <th>Visitors</th>
        <th>Date</th>
        <th>Actions</th>
      </tr>`;
  }
}

async function loadMediaFiles(page = 1) {
  currentPage = page;
  const tbody = document.getElementById("media-table-body");
  const paginationControls = document.getElementById("pagination-controls");
  const pageInfo = document.getElementById("pagination-info");

  if (!tbody) return;

  renderMediaTableHeader(currentSource);
  tbody.innerHTML = UI.stateRow(7, "loading", "Loading media items...");

  try {
    const url = `/api/media?page=${page}&page_size=10&search=${encodeURIComponent(currentSearch)}&source=${encodeURIComponent(currentSource)}`;
    const res = await API.request(url);

    if (!res.items || res.items.length === 0) {
      let emptyMsg = "No Media Files Found";
      let emptySub = "Import files via Google Drive to populate your library.";
      if (currentSource === "permanent") {
        emptyMsg = "No Permanent Items Yet";
        emptySub = "Items in the Temporary Queue will appear here once promoted to mobile accounts.";
      } else if (currentSource === "temp") {
        emptyMsg = "Temporary Queue Is Empty";
        emptySub = "All imported files have been promoted to permanent mobile accounts.";
      }

      tbody.innerHTML = `
        <tr>
          <td colspan="7">
            ${UI.emptyStateHTML("folder", emptyMsg, emptySub)}
          </td>
        </tr>`;
      if (paginationControls) paginationControls.innerHTML = "";
      if (pageInfo) pageInfo.textContent = "Showing 0 items";
      return;
    }

    window._mediaItemsMap = new Map();
    (res.items || []).forEach((it) => window._mediaItemsMap.set(it.id, it));

    tbody.innerHTML = res.items.map((item) => {
      const sizeStr = item.file_size ? ` • <span class="cell-size">${UI.formatBytes(item.file_size)}</span>` : "";
      const dlPath = item.token ? `/download/${item.token}` : null;
      const fullDlUrl = dlPath ? `${window.location.origin}${dlPath}` : null;
      const errBtn = item.error_message ? `
        <button class="icon-btn icon-btn-warning" onclick="showMediaError(${item.id})" title="View Error Details">
          ${icon("alert-triangle", 15) || icon("circle-alert", 15)}
        </button>` : "";

      const keyTag = item.api_key_name
        ? ` • <span title="Imported via API Key: ${UI.escapeHtml(item.api_key_name)}" style="color:var(--accent); font-weight:600;">🔑 ${UI.escapeHtml(item.api_key_name)}</span>`
        : "";

      const visitorsBadge = `<span class="badge badge-neutral" style="font-weight:600; font-size:0.75rem;">👁️ ${item.visitor_count || 0}</span>`;

      // Stage-specific row rendering: Permanent
      if (currentSource === "permanent") {
        return `
          <tr>
            <td data-label="File / Title">
              <div>
                <div class="cell-strong" title="${UI.escapeHtml(item.filename || item.title || "Untitled")}">${UI.escapeHtml(item.filename || item.title || "Untitled")}</div>
                <div class="cell-sub">ID: #${item.id}${sizeStr}${keyTag}</div>
              </div>
            </td>
            <td data-label="Media Key">${UI.codePill(item.media_key, "Media Key", 10)}</td>
            <td data-label="Account">
              <span class="cell-sub" style="font-weight:600; color:var(--text-primary);">
                ${item.email ? UI.escapeHtml(item.email) : "—"}
              </span>
            </td>
            <td data-label="Download Link">
              ${fullDlUrl ? UI.codePill(fullDlUrl, "Download Link", 12) : "—"}
            </td>
            <td data-label="Visitors">${visitorsBadge}</td>
            <td data-label="Promoted">${UI.formatTableDate(item.created_at)}</td>
            <td data-label="Actions" class="table-actions-cell">
              <div class="table-actions">
                ${errBtn}
                ${dlPath ? `
                  <a class="icon-btn" href="${dlPath}" target="_blank" title="Direct Download via Server">
                    ${icon("download", 14)}
                  </a>` : ""}
                <button class="icon-btn icon-btn-danger" onclick="confirmDeleteMedia('${item.media_key || ''}', '${item.dedup_key || ''}', ${item.id || 'null'}, '${item.drive_id || ''}')" title="Delete permanently">
                  ${icon("trash-2", 14)}
                </button>
              </div>
            </td>
          </tr>`;
      }

      // Stage-specific row rendering: Temporary Queue
      if (currentSource === "temp") {
        return `
          <tr>
            <td data-label="File / Title">
              <div>
                <div class="cell-strong" title="${UI.escapeHtml(item.filename || item.title || "Untitled")}">${UI.escapeHtml(item.filename || item.title || "Untitled")}</div>
                <div class="cell-sub">ID: #${item.id}${sizeStr}${keyTag}</div>
              </div>
            </td>
            <td data-label="Media Key">${UI.codePill(item.media_key, "Media Key", 9)}</td>
            <td data-label="Dedup Key">${UI.codePill(item.dedup_key, "Dedup Key", 8)}</td>
            <td data-label="Status">${UI.badge("In Web Queue", "amber")}</td>
            <td data-label="Visitors">${visitorsBadge}</td>
            <td data-label="Share Link">
              ${item.share_url ? UI.codePill(item.share_url, "Share URL", 11) : `<span class="text-muted" style="font-size:0.78rem">Pending Worker…</span>`}
            </td>
            <td data-label="Imported">${UI.formatTableDate(item.created_at)}</td>
            <td data-label="Actions" class="table-actions-cell">
              <div class="table-actions">
                ${errBtn}
                ${dlPath ? `
                  <a class="icon-btn" href="${dlPath}" target="_blank" title="Direct Download via Server">
                    ${icon("download", 14)}
                  </a>` : ""}
                <button class="icon-btn icon-btn-danger" onclick="confirmDeleteMedia('${item.media_key || ''}', '${item.dedup_key || ''}', ${item.id || 'null'}, '${item.drive_id || ''}')" title="Delete permanently">
                  ${icon("trash-2", 14)}
                </button>
              </div>
            </td>
          </tr>`;
      }

      // Default: All Files
      return `
        <tr>
          <td data-label="File / Title">
            <div>
              <div class="cell-strong" title="${UI.escapeHtml(item.filename || item.title || "Untitled")}">${UI.escapeHtml(item.filename || item.title || "Untitled")}</div>
              <div class="cell-sub">ID: #${item.id}${sizeStr}${keyTag}</div>
            </div>
          </td>
          <td data-label="Drive ID">${UI.codePill(item.drive_id, "Drive ID", 10)}</td>
          <td data-label="Stage">${stageBadge(item.stage)}</td>
          <td data-label="Download Link">
            ${fullDlUrl ? UI.codePill(fullDlUrl, "Download Link", 12) : "—"}
          </td>
          <td data-label="Visitors">${visitorsBadge}</td>
          <td data-label="Date">${UI.formatTableDate(item.created_at)}</td>
          <td data-label="Actions" class="table-actions-cell">
            <div class="table-actions">
              ${errBtn}
              ${dlPath ? `
                <a class="icon-btn" href="${dlPath}" target="_blank" title="Direct Download via Server">
                  ${icon("download", 14)}
                </a>` : ""}
              <button class="icon-btn icon-btn-danger" onclick="confirmDeleteMedia('${item.media_key || ''}', '${item.dedup_key || ''}', ${item.id || 'null'}, '${item.drive_id || ''}')" title="Delete permanently">
                ${icon("trash-2", 14)}
              </button>
            </div>
          </td>
        </tr>`;
    }).join("");

    // Render Pagination Controls
    if (pageInfo) {
      const startItem = (res.page - 1) * res.page_size + 1;
      const endItem = Math.min(res.total, res.page * res.page_size);
      pageInfo.textContent = `Showing ${startItem}-${endItem} of ${res.total} media items`;
    }

    UI.renderPagination(paginationControls, res, loadMediaFiles);
  } catch (err) {
    tbody.innerHTML = UI.stateRow(7, "error", `Failed to load media files: ${err.message}`);
  }
}

/**
 * Display full error details in modal dialog
 */
function showMediaError(id) {
  const item = (window._mediaItemsMap && window._mediaItemsMap.get(id)) || null;
  if (!item || !item.error_message) return;
  const modal = document.getElementById("error-details-modal");
  if (!modal) return;

  const fileEl = document.getElementById("error-modal-file");
  const driveEl = document.getElementById("error-modal-drive-id");
  const badgeEl = document.getElementById("error-modal-badge");
  const contentEl = document.getElementById("error-modal-content");

  if (fileEl) fileEl.textContent = item.filename || item.title || "Untitled";
  if (driveEl) driveEl.textContent = item.drive_id || item.drive_file_id || "—";
  if (badgeEl) {
    if (item.stage === "unsupported") {
      badgeEl.textContent = "Format Unsupported";
      badgeEl.className = "badge badge-rose";
    } else if (item.stage === "not_found") {
      badgeEl.textContent = "Drive Missing";
      badgeEl.className = "badge badge-rose";
    } else {
      badgeEl.textContent = "Import Failed";
      badgeEl.className = "badge badge-amber";
    }
  }
  if (contentEl) contentEl.textContent = item.error_message;

  if (typeof window.hydrateIcons === "function") {
    window.hydrateIcons(modal);
  }

  UI.openModal(modal);
}
window.showMediaError = showMediaError;

function setupMediaErrorModal() {
  const modal = document.getElementById("error-details-modal");
  if (!modal) return;
  const closeBtn = document.getElementById("close-error-modal");
  const actionBtn = document.getElementById("close-error-btn");
  const copyBtn = document.getElementById("copy-error-btn");

  if (closeBtn) closeBtn.addEventListener("click", () => UI.closeModal(modal));
  if (actionBtn) actionBtn.addEventListener("click", () => UI.closeModal(modal));
  if (copyBtn) {
    copyBtn.addEventListener("click", () => {
      const contentEl = document.getElementById("error-modal-content");
      if (contentEl && contentEl.textContent) {
        if (typeof copyToClipboard === "function") {
          copyToClipboard(contentEl.textContent);
        } else if (navigator.clipboard) {
          navigator.clipboard.writeText(contentEl.textContent).then(() => {
            if (typeof Toast !== "undefined") Toast.show("Error log copied to clipboard", "success");
          });
        }
      }
    });
  }
  modal.addEventListener("click", (e) => {
    if (e.target === modal) UI.closeModal(modal);
  });
}

/**
 * Drive Importer Form
 */
function setupDriveImportForm() {
  const form = document.getElementById("drive-import-form");
  const resultCard = document.getElementById("drive-import-result");

  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    let driveInput = form.drive_file_id.value.trim();
    const mimeType = form.mime_type.value.trim();
    const cleanup = form.cleanup.checked;
    const submitBtn = form.querySelector("button[type='submit']");

    // Auto extract Drive File ID if full URL pasted
    if (driveInput.includes("drive.google.com")) {
      const match = driveInput.match(/\/d\/([a-zA-Z0-9_-]+)/);
      if (match) driveInput = match[1];
    }

    if (!driveInput) {
      Toast.show("Please enter a valid Google Drive File ID", "error");
      return;
    }

    const reset = UI.setBusy(submitBtn, "Importing your file...");
    if (resultCard) resultCard.hidden = true;

    try {
      const res = await API.request("/api/web/import-drive", {
        method: "POST",
        body: {
          drive_file_id: driveInput,
          mime_type: mimeType || "video/*",
          cleanup: cleanup,
        },
      });

      Toast.show("File successfully imported to Google Photos!", "success");
      form.reset();

      if (resultCard) {
        document.getElementById("drive-res-media-key").textContent = res.media_key;
        document.getElementById("drive-res-dedup-key").textContent = res.dedup_key || "-";
        const dlBtn = document.getElementById("drive-res-download-btn");
        if (dlBtn) {
          dlBtn.onclick = () => copyToClipboard(res.download_url, "Download URL");
        }
        resultCard.hidden = false;
      }

      loadDashboardStats();
      loadMediaFiles(1);
    } catch (err) {
      Toast.show(err.message || "Drive import failed", "error");
    } finally {
      reset();
    }
  });
}

/**
 * Share Link Importer Form
 */
function setupShareImportForm() {
  const form = document.getElementById("share-import-form");

  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const shareUrl = form.share_url.value.trim();
    const submitBtn = form.querySelector("button[type='submit']");

    if (!shareUrl) {
      Toast.show("Please enter a Google Photos public share link", "error");
      return;
    }

    const reset = UI.setBusy(submitBtn, "Scraping & Importing...");

    try {
      const res = await API.request("/api/mobile/import-shared", {
        method: "POST",
        body: { share_url: shareUrl },
      });

      if (res.success) {
        Toast.show(`Imported ${res.media_count} item(s) successfully!`, "success");
      } else {
        Toast.show(`Import completed with status ${res.status}: ${res.status_message}`, "info");
      }

      form.reset();
      loadDashboardStats();
      loadMediaFiles(1);
    } catch (err) {
      Toast.show(err.message || "Share import failed", "error");
    } finally {
      reset();
    }
  });
}

/**
 * Web Cookie Sessions Management
 */
function setupSessionManager() {
  UI.bindModal("add-session-modal", "open-add-session-modal", "close-session-modal");
  UI.bindModal("view-session-modal", null, "close-view-session-modal");
  UI.bindModal("quota-modal", null, "close-quota-modal");

  const closeViewBtn = document.getElementById("close-view-sess-btn");
  if (closeViewBtn) {
    closeViewBtn.addEventListener("click", () => {
      const modal = document.getElementById("view-session-modal");
      if (modal) UI.closeModal(modal);
    });
  }

  const closeQuotaBtn = document.getElementById("close-quota-btn");
  if (closeQuotaBtn) {
    closeQuotaBtn.addEventListener("click", () => {
      const modal = document.getElementById("quota-modal");
      if (modal) UI.closeModal(modal);
    });
  }

  const modal = document.getElementById("add-session-modal");
  const form = document.getElementById("add-session-form");

  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const cookies = form.raw_cookies.value.trim();
      const submitBtn = form.querySelector("button[type='submit']");

      if (!cookies) {
        Toast.show("Cookies are required", "error");
        return;
      }

      const reset = UI.setBusy(submitBtn, "Verifying with Google Photos...");

      try {
        await API.request("/api/web/sessions", {
          method: "POST",
          body: { cookies },
        });

        Toast.show("Session added & verified successfully!", "success");
        form.reset();
        UI.closeModal(modal);
        loadWebSessions();
        loadDashboardStats();
      } catch (err) {
        Toast.show(err.message || "Failed to add session", "error");
      } finally {
        reset();
      }
    });
  }
}

async function loadWebSessions() {
  const tbody = document.getElementById("sessions-table-body");
  if (!tbody) return;

  tbody.innerHTML = UI.stateRow(4, "loading", "Loading cookie sessions...");

  try {
    const sessions = await API.request("/api/web/sessions");
    if (!sessions || sessions.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="4">
            ${UI.emptyStateHTML("cookie", "No Cookie Sessions Yet", 'Click "Add Session" above to register your Google Photos web session.')}
          </td>
        </tr>`;
      return;
    }

    tbody.innerHTML = sessions.map((s) => `
      <tr>
        <td data-label="Account">
          <a href="javascript:void(0)" onclick="viewSession('${s.session_id}')" class="cell-strong" style="color:var(--accent-primary);text-decoration:none;cursor:pointer;border-bottom:1px dashed var(--accent-primary)" title="Click to view full session details">
            ${UI.codePill(s.account_email || "Google Account", "Account Email", 22)}
          </a>
        </td>
        <td data-label="Status">
          ${s.is_active ? UI.badge("Active", "emerald") : UI.badge("Expired", "rose")}
        </td>
        <td data-label="Updated"><span class="cell-date">${UI.formatDate(s.updated_at)}</span></td>
        <td data-label="Actions" class="table-actions-cell">
          <div class="table-actions">
            <button class="btn btn-secondary btn-sm" onclick="checkSessionStatus('${s.session_id}')" title="Test session status">
              ${icon("zap", 14)} Test
            </button>
            <button class="btn btn-secondary btn-sm" onclick="checkSessionQuota('${s.session_id}')" title="Check storage quota">
              ${icon("database", 14)} Quota
            </button>
            <button class="btn btn-danger btn-sm" onclick="deleteSession('${s.session_id}')" title="Delete session">
              ${icon("trash-2", 14)}
            </button>
          </div>
        </td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = UI.stateRow(4, "error", `Failed to load sessions: ${err.message}`);
  }
}

async function viewSession(sessionId) {
  try {
    Toast.show("Loading session details...", "info", 1000);
    const s = await API.request(`/api/web/sessions/${encodeURIComponent(sessionId)}`);

    const nameEl = document.getElementById("view-sess-name");
    const accountEl = document.getElementById("view-sess-account");
    const idEl = document.getElementById("view-sess-id");
    const statusEl = document.getElementById("view-sess-status");

    if (nameEl) nameEl.textContent = s.name || "—";
    if (accountEl) accountEl.textContent = s.account_email || "—";
    if (idEl) idEl.textContent = s.session_id || "—";
    if (statusEl) {
      statusEl.innerHTML = s.is_active ? UI.badge("Active", "emerald") : UI.badge("Expired", "rose");
    }

    const createdEl = document.getElementById("view-sess-created");
    const updatedEl = document.getElementById("view-sess-updated");
    if (createdEl) createdEl.textContent = s.created_at ? UI.formatDate(s.created_at) : "—";
    if (updatedEl) updatedEl.textContent = s.updated_at ? UI.formatDate(s.updated_at) : "—";

    const blobEl = document.getElementById("view-sess-blob");
    const blobCopyBtn = document.getElementById("copy-sess-blob-btn");

    if (blobEl) {
      blobEl.value = s.session_blob_json || "(No session blob saved in DB)";
    }

    if (blobCopyBtn) {
      blobCopyBtn.onclick = () => {
        const content = blobEl ? blobEl.value : "";
        if (!content || content.startsWith("(")) {
          Toast.show("No session blob saved in DB", "info");
          return;
        }
        navigator.clipboard.writeText(content)
          .then(() => Toast.show("Session blob JSON copied!", "success"))
          .catch(() => Toast.show("Failed to copy blob", "error"));
      };
    }

    // Wire delete button inside view modal
    const deleteBtn = document.getElementById("delete-view-sess-btn");
    if (deleteBtn) {
      deleteBtn.onclick = async () => {
        const modal = document.getElementById("view-session-modal");
        if (modal) UI.closeModal(modal);
        await deleteSession(s.session_id);
      };
    }

    const modal = document.getElementById("view-session-modal");
    if (modal) {
      UI.openModal(modal);
      if (typeof window.renderIcons === "function") window.renderIcons();
    }
  } catch (err) {
    Toast.show(`Failed to load session details: ${err.message}`, "error");
  }
}


async function checkSessionStatus(sessionId) {
  try {
    const res = await API.request(`/api/web/sessions/${sessionId}/check`, { method: "POST" });
    if (res.valid) {
      Toast.show(`Session is VALID! Account: ${res.account || "Google User"}`, "success");
    } else {
      Toast.show(`Session is INVALID: ${res.message}`, "error");
    }
  } catch (err) {
    Toast.show(`Check failed: ${err.message}`, "error");
  } finally {
    if (typeof loadWebSessions === "function") {
      await loadWebSessions();
    }
  }
}

async function checkSessionQuota(sessionId) {
  const modal = document.getElementById('quota-modal');
  const body = document.getElementById('quota-modal-body');
  try {
    Toast.show("Fetching storage quota...", "info", 1200);
    const res = await API.request(`/api/web/quota?session_id=${encodeURIComponent(sessionId)}`);

    const usedPct    = res.used_percent != null ? Number(res.used_percent).toFixed(1) : '?';
    const freePct    = res.free_percent != null ? Number(res.free_percent).toFixed(1) : '?';
    const usedBytes  = res.used_display || (res.used_bytes ? (res.used_bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB' : '?');
    const totalBytes = res.total_display || (res.total_bytes ? Math.round(res.total_bytes / (1024 * 1024 * 1024)) + ' GB' : '?');
    const barPct     = Math.min(Math.max(parseFloat(usedPct) || 0, 0), 100);
    const barColor   = barPct > 90 ? 'var(--accent-rose, #ef4444)' : barPct > 70 ? 'var(--accent-amber, #f59e0b)' : 'var(--accent-emerald, #10b981)';
    const statusBadge = barPct > 95
      ? UI.badge("Almost Full", "rose")
      : barPct > 75
      ? UI.badge("High Usage", "amber")
      : UI.badge("Healthy", "emerald");

    if (body) {
      body.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.25rem;">
          <div>
            <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px;">Session ID</div>
            <div class="code-pill" style="margin-top: 0.25rem; font-size: 0.82rem;">${UI.escapeHtml(sessionId)}</div>
          </div>
          <div style="text-align: right;">
            <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px;">Status</div>
            <div style="margin-top: 0.25rem;">${statusBadge}</div>
          </div>
        </div>

        <div style="background: var(--bg-inset, rgba(0,0,0,0.03)); border: 1px solid var(--border, rgba(255,255,255,0.08)); border-radius: 12px; padding: 1.25rem; margin-bottom: 1.25rem;">
          <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.6rem;">
            <span style="font-size: 1.05rem; font-weight: 600; color: var(--text-primary);">
              ${UI.escapeHtml(res.usage_text || `${usedBytes} of ${totalBytes} used`)}
            </span>
            <span style="font-weight: 700; font-size: 1.05rem; color: ${barColor};">
              ${usedPct}%
            </span>
          </div>
          <div style="height: 10px; border-radius: 5px; background: rgba(125, 125, 125, 0.15); overflow: hidden; position: relative;">
            <div style="height: 100%; width: ${barPct}%; background: ${barColor}; border-radius: 5px; transition: width 0.5s ease-out;"></div>
          </div>
          <div style="display: flex; justify-content: space-between; margin-top: 0.5rem; font-size: 0.8rem; color: var(--text-muted);">
            <span>Used: ${usedBytes}</span>
            <span>Free: ${freePct}%</span>
          </div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem;">
          <div style="background: var(--bg-surface, rgba(255,255,255,0.02)); border: 1px solid var(--border, rgba(255,255,255,0.06)); padding: 0.85rem 1rem; border-radius: 10px;">
            <div style="font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase; font-weight: 600;">Total Storage</div>
            <div style="font-size: 1rem; font-weight: 600; color: var(--text-primary); margin-top: 0.2rem;">${totalBytes}</div>
          </div>
          <div style="background: var(--bg-surface, rgba(255,255,255,0.02)); border: 1px solid var(--border, rgba(255,255,255,0.06)); padding: 0.85rem 1rem; border-radius: 10px;">
            <div style="font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase; font-weight: 600;">Available Free</div>
            <div style="font-size: 1rem; font-weight: 600; color: var(--accent-emerald, #10b981); margin-top: 0.2rem;">${freePct}% free</div>
          </div>
        </div>

        ${barPct > 95 ? `
          <div style="margin-top: 1rem; padding: 0.75rem 1rem; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.25); border-radius: 8px; font-size: 0.82rem; color: #ef4444; display: flex; align-items: center; gap: 0.5rem;">
            <span data-icon="alert-circle" data-size="16"></span>
            <span><strong>Storage Critical:</strong> Account is ${usedPct}% full. Imports may fail when storage reaches 100%.</span>
          </div>
        ` : ''}
      `;
    }

    if (modal) {
      UI.openModal(modal);
      if (typeof window.renderIcons === 'function') window.renderIcons();
    }
  } catch (err) {
    Toast.show(`Quota fetch failed: ${err.message}`, "error");
  }
}

async function deleteSession(sessionId) {
  const ok = await UI.confirm({
    title: "Delete Cookie Session?",
    message: "This will permanently remove the stored Google Photos web session. This action cannot be undone.",
    confirmText: "Delete",
  });
  if (!ok) return;

  try {
    await API.request(`/api/web/sessions/${sessionId}`, { method: "DELETE" });
    Toast.show("Session deleted successfully", "success");
    loadWebSessions();
    loadDashboardStats();
  } catch (err) {
    Toast.show(err.message, "error");
  }
}

/**
 * Mobile Auth Accounts Management
 */
function setupMobileManager() {
  UI.bindModal("add-mobile-modal", "open-add-mobile-modal", "close-mobile-modal");

  const modal = document.getElementById("add-mobile-modal");
  const form = document.getElementById("add-mobile-form");

  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const authData = form.auth_data.value.trim();
      const submitBtn = form.querySelector("button[type='submit']");

      if (!authData) {
        Toast.show("AUTH_DATA string is required", "error");
        return;
      }

      const reset = UI.setBusy(submitBtn, "Verifying your account...");

      try {
        const res = await API.request("/api/mobile/accounts", {
          method: "POST",
          body: { auth_data: authData },
        });

        Toast.show(`Mobile account ${res.email} saved successfully!`, "success");
        form.reset();
        UI.closeModal(modal);
        loadMobileAccounts();
        loadDashboardStats();
      } catch (err) {
        Toast.show(err.message || "Failed to register mobile account", "error");
      } finally {
        reset();
      }
    });
  }
}

async function loadMobileAccounts() {
  const tbody = document.getElementById("mobile-table-body");
  if (!tbody) return;

  tbody.innerHTML = UI.stateRow(4, "loading", "Loading mobile accounts...");

  try {
    const accounts = await API.request("/api/mobile/accounts");
    if (!accounts || accounts.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="4">
            ${UI.emptyStateHTML("smartphone", "No Mobile Accounts Yet", "Click \"Add Mobile Account\" above to register your first GPMC mobile client.")}
          </td>
        </tr>`;
      return;
    }

    tbody.innerHTML = accounts.map((a) => `
      <tr>
        <td data-label="Account"><span class="cell-strong">${UI.escapeHtml(a.email)}</span></td>
        <td data-label="Status">
          ${a.is_active ? UI.badge("Active Primary", "emerald") : UI.badge("Standby", "violet")}
        </td>
        <td data-label="Updated"><span class="cell-date">${UI.formatDate(a.updated_at)}</span></td>
        <td data-label="Actions" class="table-actions-cell">
          <div class="table-actions">
            ${!a.is_active ? `<button class="btn btn-secondary btn-sm" onclick="activateMobileAccount(${a.id})">${icon("check", 14)} Set Active</button>` : ""}
            <button class="btn btn-danger btn-sm" onclick="deleteMobileAccount(${a.id})" title="Remove account">
              ${icon("trash-2", 14)}
            </button>
          </div>
        </td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = UI.stateRow(4, "error", `Failed to load accounts: ${err.message}`);
  }
}

async function activateMobileAccount(accountId) {
  try {
    await API.request(`/api/mobile/accounts/${accountId}/activate`, { method: "PUT" });
    Toast.show("Active mobile account updated", "success");
    loadMobileAccounts();
  } catch (err) {
    Toast.show(err.message, "error");
  }
}

async function deleteMobileAccount(accountId) {
  const ok = await UI.confirm({
    title: "Remove Mobile Account?",
    message: "The stored AUTH_DATA and tokens for this account will be permanently deleted from the database.",
    confirmText: "Remove",
  });
  if (!ok) return;

  try {
    await API.request(`/api/mobile/accounts/${accountId}`, { method: "DELETE" });
    Toast.show("Account deleted", "success");
    loadMobileAccounts();
    loadDashboardStats();
  } catch (err) {
    Toast.show(err.message, "error");
  }
}

/**
 * Admins Management
 */
function setupAdminManager() {
  UI.bindModal("add-admin-modal", "open-add-admin-modal", "close-add-admin-modal");

  const cancelBtn = document.getElementById("cancel-add-admin-btn");
  const modal = document.getElementById("add-admin-modal");
  if (cancelBtn && modal) {
    cancelBtn.addEventListener("click", () => UI.closeModal(modal));
  }

  const form = document.getElementById("create-admin-form");
  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const username = form.new_username.value.trim();
      const password = form.new_password.value;
      const submitBtn = form.querySelector("button[type='submit']");

      if (!username || !password) {
        Toast.show("Username and password required", "error");
        return;
      }

      const reset = UI.setBusy(submitBtn, "Creating...");
      try {
        await API.request("/api/auth/admins", {
          method: "POST",
          body: { username, password },
        });

        Toast.show(`Admin '${username}' created successfully!`, "success");
        form.reset();
        if (modal) UI.closeModal(modal);
        loadAdmins();
      } catch (err) {
        Toast.show(err.message || "Failed to create admin", "error");
      } finally {
        reset();
      }
    });
  }
}

async function loadAdmins() {
  const tbody = document.getElementById("admins-table-body");
  if (!tbody) return;

  tbody.innerHTML = UI.stateRow(4, "loading", "Loading administrators...");

  try {
    const admins = await API.request("/api/auth/admins");
    if (!admins || admins.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="4">
            ${UI.emptyStateHTML("shield-check", "No Administrators", "Create the first administrator using the form on the left.")}
          </td>
        </tr>`;
      return;
    }

    tbody.innerHTML = admins.map((adm) => `
      <tr>
        <td data-label="Username"><span class="cell-strong">${UI.escapeHtml(adm.username)}</span></td>
        <td data-label="Status">
          ${adm.is_active ? UI.badge("Active", "emerald") : UI.badge("Inactive", "rose")}
        </td>
        <td data-label="Created"><span class="cell-date">${UI.formatDate(adm.created_at)}</span></td>
        <td data-label="Action" class="table-actions-cell">
          <div class="table-actions">
            <button class="btn btn-danger btn-sm" onclick="deleteAdmin(${adm.id})" title="Delete admin">
              ${icon("trash-2", 14)} Delete
            </button>
          </div>
        </td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = UI.stateRow(4, "error", `Failed to load admins: ${err.message}`);
  }
}

async function deleteAdmin(adminId) {
  const ok = await UI.confirm({
    title: "Delete Administrator?",
    message: "This administrator will lose access immediately. This action cannot be undone.",
    confirmText: "Delete",
  });
  if (!ok) return;

  try {
    await API.request(`/api/auth/admins/${adminId}`, { method: "DELETE" });
    Toast.show("Admin removed", "success");
    loadAdmins();
  } catch (err) {
    Toast.show(err.message, "error");
  }
}

/**
 * Import Concurrency Setting
 */
function setupConcurrencySetting() {
  const btn = document.getElementById("save-concurrency-btn");
  const input = document.getElementById("max_concurrent_imports");
  const slider = document.getElementById("concurrency-slider");
  const chip = document.getElementById("concurrency-value-chip");
  const statusBadge = document.getElementById("concurrency-status-badge");
  if (!btn || !input) return;

  const clamp = (v) => Math.min(50, Math.max(1, parseInt(v, 10) || 1));
  const syncUI = (value) => {
    const v = clamp(value);
    input.value = v;
    if (slider) slider.value = v;
    if (chip) chip.textContent = `${v} slot${v > 1 ? "s" : ""}`;
  };

  if (slider) slider.addEventListener("input", () => syncUI(slider.value));
  input.addEventListener("input", () => {
    if (input.value === "") return;
    const v = clamp(input.value);
    if (slider) slider.value = v;
    if (chip) chip.textContent = `${v} slot${v > 1 ? "s" : ""}`;
  });

  document.querySelectorAll("#concurrency-presets .conc-preset").forEach((preset) => {
    preset.addEventListener("click", () => syncUI(preset.dataset.value));
  });

  btn.addEventListener("click", async () => {
    const value = clamp(input.value);
    if (value < 1 || value > 50) {
      Toast.show("Value must be between 1 and 50", "error");
      return;
    }
    const reset = UI.setBusy(btn, "Saving...");
    try {
      const data = await API.request("/api/settings/import-concurrency", {
        method: "POST",
        body: { max_concurrent_imports: value },
      });
      if (statusBadge) statusBadge.textContent = `${data.max_concurrent_imports} slot${data.max_concurrent_imports > 1 ? "s" : ""}`;
      syncUI(data.max_concurrent_imports);
      Toast.show(`Concurrency set to ${data.max_concurrent_imports}`, "success");
    } catch (err) {
      Toast.show(err.message || "Failed to save concurrency setting", "error");
    } finally {
      reset();
    }
  });
}

async function loadConcurrencySetting() {
  const input = document.getElementById("max_concurrent_imports");
  const slider = document.getElementById("concurrency-slider");
  const badge = document.getElementById("concurrency-status-badge");
  const chip = document.getElementById("concurrency-value-chip");
  if (!input) return;
  try {
    const data = await API.request("/api/settings/import-concurrency");
    input.value = data.max_concurrent_imports;
    if (slider) slider.value = data.max_concurrent_imports;
    const label = `${data.max_concurrent_imports} slot${data.max_concurrent_imports > 1 ? "s" : ""}`;
    if (badge) badge.textContent = label;
    if (chip) chip.textContent = label;
  } catch (_) { /* non-critical */ }
}

/**
 * Google Drive API Key Settings
 */
function setupDriveApiKeySetting() {
  const form = document.getElementById("drive-api-key-form");
  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const apiKeyInput = document.getElementById("drive_api_key");
      const apiKey = apiKeyInput.value.trim();
      const submitBtn = document.getElementById("save-drive-key-btn");

      if (!apiKey) {
        Toast.show("API Key cannot be empty", "error");
        return;
      }

      const reset = UI.setBusy(submitBtn, "Saving...");
      try {
        await API.request("/api/settings/drive-api-key", {
          method: "POST",
          body: { api_key: apiKey },
        });
        Toast.show("Google Drive API key saved successfully!", "success");
        await loadDriveApiKeySetting();
      } catch (err) {
        Toast.show(err.message || "Failed to save Drive API key", "error");
      } finally {
        reset();
      }
    });
  }
}

async function loadDriveApiKeySetting() {
  const input = document.getElementById("drive_api_key");
  const badge = document.getElementById("drive-key-status-badge");
  if (!input) return;

  try {
    const data = await API.request("/api/settings/drive-api-key");
    if (data && data.api_key) {
      input.value = data.api_key;
      if (badge) {
        badge.textContent = "Configured";
        badge.className = "badge badge-success";
      }
    } else {
      if (badge) {
        badge.textContent = "Not Set";
        badge.className = "badge badge-warning";
      }
    }
  } catch (err) {
    if (badge) {
      badge.textContent = "Error";
      badge.className = "badge badge-danger";
    }
  }
}

/**
 * Danger Zone: Full Media Database Reset Modal
 */
function openResetMediaModal() {
  const modal = document.getElementById("reset-media-modal");
  const input = document.getElementById("reset-media-confirm-input");
  const confirmBtn = document.getElementById("confirm-reset-media-btn");

  if (input) input.value = "";
  if (confirmBtn) {
    confirmBtn.disabled = true;
    confirmBtn.innerHTML = `${icon("trash-2", 15)} Wipe All Media`;
  }
  if (modal) {
    UI.openModal(modal);
    if (typeof window.renderIcons === "function") window.renderIcons();
    setTimeout(() => { if (input) input.focus(); }, 100);
  }
}

function setupResetMediaModal() {
  const modal = document.getElementById("reset-media-modal");
  const input = document.getElementById("reset-media-confirm-input");
  const confirmBtn = document.getElementById("confirm-reset-media-btn");
  const cancelBtn = document.getElementById("cancel-reset-media-btn");
  const closeBtn = document.getElementById("close-reset-media-modal");

  if (!modal) return;

  if (input && confirmBtn) {
    input.addEventListener("input", () => {
      confirmBtn.disabled = input.value.trim().toUpperCase() !== "RESET";
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !confirmBtn.disabled) {
        confirmBtn.click();
      }
    });
  }

  const closeModal = () => {
    UI.closeModal(modal);
    if (input) input.value = "";
    if (confirmBtn) confirmBtn.disabled = true;
  };

  if (cancelBtn) cancelBtn.onclick = closeModal;
  if (closeBtn) closeBtn.onclick = closeModal;

  if (confirmBtn) {
    confirmBtn.onclick = async () => {
      if (input && input.value.trim().toUpperCase() !== "RESET") return;

      const reset = UI.setBusy(confirmBtn, "Wiping database...");
      try {
        const res = await API.request("/api/media/reset-all", {
          method: "POST",
          body: { confirm: "RESET" },
        });
        Toast.show(res.message || "All media database wiped successfully!", "success");
        closeModal();
        loadDashboardStats();
        loadMediaFiles(1);
      } catch (err) {
        Toast.show(err.message || "Reset failed", "error");
      } finally {
        reset();
      }
    };
  }
}

/**
 * Shared Actions (Download, Share Link, Delete)
 */
async function getAndCopyDownloadURL(mediaKey) {
  Toast.show("Resolving download URL...", "info", 1500);
  try {
    // Try Web Client first, falls back to Mobile Client if needed
    let res;
    try {
      res = await API.request(`/api/web/download-url?media_key=${encodeURIComponent(mediaKey)}`);
    } catch (e) {
      res = await API.request(`/api/mobile/download-url?media_key=${encodeURIComponent(mediaKey)}`);
    }

    if (res && res.download_url) {
      copyToClipboard(res.download_url, "Direct Download Link");
      if (res.cached) {
        Toast.show("Served instantly from cache!", "success", 2000);
      }
    }
  } catch (err) {
    Toast.show(`Download link resolution failed: ${err.message}`, "error");
  }
}

async function getAndCopyShareLink(mediaKey) {
  Toast.show("Generating public share link...", "info", 1500);
  try {
    let res;
    try {
      res = await API.request("/api/web/share-link", {
        method: "POST",
        body: { media_key: mediaKey },
      });
    } catch (e) {
      res = await API.request("/api/mobile/share-link", {
        method: "POST",
        body: { media_keys: [mediaKey] },
      });
    }

    if (res && res.share_url) {
      copyToClipboard(res.share_url, "Public Share Link");
    }
  } catch (err) {
    Toast.show(`Share link generation failed: ${err.message}`, "error");
  }
}

async function confirmDeleteMedia(mediaKey, dedupKey, refId, driveId) {
  const itemLabel = mediaKey ? `item (${mediaKey.slice(0, 16)}…)` : (driveId ? `Drive file (${driveId})` : "this item");
  const ok = await UI.confirm({
    title: "Delete Media Item?",
    message: `Are you sure you want to permanently delete ${itemLabel}? This action cannot be undone.`,
    confirmText: "Delete",
    danger: true,
  });
  if (!ok) return;

  Toast.show("Deleting item...", "info", 1500);
  try {
    await API.request("/api/web/delete", {
      method: "POST",
      body: {
        dedup_key: dedupKey || undefined,
        media_key: mediaKey || undefined,
        drive_ref_id: refId || undefined,
        drive_id: driveId || undefined,
      },
    });

    Toast.show("Media deleted successfully", "success");
    loadDashboardStats();
    loadMediaFiles(currentPage);
  } catch (err) {
    Toast.show(`Delete failed: ${err.message}`, "error");
  }
}

async function confirmRequeueErrorFiles() {
  const ok = await UI.confirm({
    title: "Re-queue Error Files?",
    message: "Are you sure you want to reset all temporary error files (Drive Error) back to queued status to retry import? Note: Permanently unsupported formats (.rar, .zip) and missing files (Not Found) are strictly skipped and will NOT be re-queued.",
    confirmText: "Yes, Re-queue Errors",
    danger: false,
  });
  if (!ok) return;

  Toast.show("Re-queueing error files...", "info", 2000);
  try {
    const res = await API.request("/api/media/requeue-errors", { method: "POST" });
    Toast.show(res.message || "Error files re-queued", "success");
    loadDashboardStats();
    loadMediaFiles(1);
  } catch (err) {
    Toast.show(`Re-queue error files failed: ${err.message}`, "error");
  }
}

async function confirmClearErrorFiles() {
  const ok = await UI.confirm({
    title: "Delete Failed, Unsupported & Missing Files?",
    message: "Are you sure you want to delete all failed (Drive Error), unsupported (.rar, .zip), and missing (Not Found) files from the database? This permanently removes them so they can be re-imported if needed.",
    confirmText: "Yes, Delete Files",
    danger: true,
  });
  if (!ok) return;

  Toast.show("Deleting error files...", "info", 2000);
  try {
    const res = await API.request("/api/media/clear-errors", { method: "POST" });
    Toast.show(res.message || "Error files deleted", "success");
    loadDashboardStats();
    loadMediaFiles(1);
  } catch (err) {
    Toast.show(`Delete error files failed: ${err.message}`, "error");
  }
}

async function confirmClearTempQueue() {
  const ok = await UI.confirm({
    title: "Delete All Temporary Items?",
    message: "Are you sure you want to delete all items in the Temporary Queue? If a valid cookie session is active, files will be removed from Google Photos. All temporary import records will be permanently removed from the local database.",
    confirmText: "Yes, Delete All Temp",
    danger: true,
  });
  if (!ok) return;

  Toast.show("Clearing temporary queue...", "info", 3000);
  try {
    const res = await API.request("/api/media/clear-temp", { method: "POST" });
    Toast.show(res.message || "Temporary queue cleared", "success");
    loadDashboardStats();
    loadMediaFiles(1);
  } catch (err) {
    Toast.show(`Clear temporary queue failed: ${err.message}`, "error");
  }
}

async function confirmClearPermanentLibrary() {
  const ok = await UI.confirm({
    title: "Delete All Permanent Library Items?",
    message: "Are you sure you want to delete ALL items in the Permanent Library? This will remove all permanent media records from the database and unlink their Google Drive references. This action cannot be undone.",
    confirmText: "Yes, Delete All Permanent",
    danger: true,
  });
  if (!ok) return;

  Toast.show("Clearing permanent library...", "info", 3000);
  try {
    const res = await API.request("/api/media/clear-permanent", { method: "POST" });
    Toast.show(res.message || "Permanent library cleared", "success");
    loadDashboardStats();
    loadMediaFiles(1);
  } catch (err) {
    Toast.show(`Clear permanent library failed: ${err.message}`, "error");
  }
}

/**
 * Developer API Keys Manager
 */
function setupApiKeyManager() {
  const openBtn = document.getElementById("open-add-key-modal");
  const modal = document.getElementById("add-key-modal");
  const closeBtn = document.getElementById("close-key-modal");
  const form = document.getElementById("add-key-form");

  const showModal = document.getElementById("show-key-modal");
  const closeShowBtn = document.getElementById("close-show-key-modal");
  const copyBtn = document.getElementById("copy-new-key-btn");
  const keyDisplay = document.getElementById("newly-generated-key");

  if (openBtn && modal) {
    openBtn.addEventListener("click", () => {
      form.reset();
      UI.showModal("add-key-modal");
    });
  }

  if (closeBtn) {
    closeBtn.addEventListener("click", () => UI.hideModal("add-key-modal"));
  }

  if (closeShowBtn) {
    closeShowBtn.addEventListener("click", () => UI.hideModal("show-key-modal"));
  }

  if (copyBtn && keyDisplay) {
    copyBtn.addEventListener("click", () => {
      copyToClipboard(keyDisplay.textContent, "Secret API Key");
    });
  }

  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const name = form.key_name.value.trim();
      const daysVal = form.key_days.value.trim();
      const expires_days = daysVal ? parseInt(daysVal, 10) : null;

      if (!name) {
        Toast.show("Please enter an API Key name", "error");
        return;
      }

      const submitBtn = form.querySelector('button[type="submit"]');
      const reset = UI.setBusy(submitBtn, "Generating Key...");

      try {
        const res = await API.request("/api/keys", {
          method: "POST",
          body: { name, expires_days },
        });

        UI.hideModal("add-key-modal");

        // Show newly generated key
        if (keyDisplay && res.api_key) {
          keyDisplay.textContent = res.api_key;
          UI.showModal("show-key-modal");
        }

        Toast.show("API Key created successfully!", "success");
        loadApiKeys();
      } catch (err) {
        Toast.show(err.message || "Failed to generate API Key", "error");
      } finally {
        reset();
      }
    });
  }

  // Edit API Key Modal handlers
  const closeEditBtn = document.getElementById("close-edit-key-modal");
  const cancelEditBtn = document.getElementById("cancel-edit-key-btn");
  const editForm = document.getElementById("edit-key-form");

  if (closeEditBtn) closeEditBtn.addEventListener("click", () => UI.hideModal("edit-key-modal"));
  if (cancelEditBtn) cancelEditBtn.addEventListener("click", () => UI.hideModal("edit-key-modal"));

  if (editForm) {
    editForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const keyId = document.getElementById("edit-key-id").value;
      const name = document.getElementById("edit-key-name").value.trim();
      const is_active = document.getElementById("edit-key-status").value === "true";
      const mode = document.getElementById("edit-key-expiry-mode").value;

      if (!name) {
        Toast.show("Please enter an API Key name", "error");
        return;
      }

      let expires_days = null;
      if (mode === "permanent") {
        expires_days = 0;
      } else if (mode === "extend") {
        const daysVal = document.getElementById("edit-key-days").value.trim();
        expires_days = daysVal ? parseInt(daysVal, 10) : null;
        if (!expires_days || expires_days <= 0) {
          Toast.show("Please enter a valid number of days", "error");
          return;
        }
      }

      const submitBtn = editForm.querySelector('button[type="submit"]');
      const reset = UI.setBusy(submitBtn, "Saving...");

      try {
        await API.request(`/api/keys/${keyId}`, {
          method: "PATCH",
          body: { name, is_active, expires_days },
        });

        UI.hideModal("edit-key-modal");
        Toast.show("API Key updated successfully!", "success");
        loadApiKeys();
      } catch (err) {
        Toast.show(err.message || "Failed to update API Key", "error");
      } finally {
        reset();
      }
    });
  }
}

window.openEditApiKeyModal = function(id, name, prefix, isActive, expiresAt) {
  document.getElementById("edit-key-id").value = id;
  document.getElementById("edit-key-name").value = name || "";
  document.getElementById("edit-key-prefix-display").textContent = prefix || "";
  document.getElementById("edit-key-status").value = isActive ? "true" : "false";

  const expiryEl = document.getElementById("edit-key-current-expiry");
  if (expiryEl) {
    expiryEl.textContent = expiresAt
      ? `Current expiry: ${UI.formatDate(expiresAt)}`
      : "Current expiry: Permanent (never expires)";
  }

  const modeSelect = document.getElementById("edit-key-expiry-mode");
  if (modeSelect) modeSelect.value = "keep";
  window.handleEditKeyExpiryChange();

  UI.showModal("edit-key-modal");
};

window.closeEditApiKeyModal = function() {
  UI.hideModal("edit-key-modal");
};

window.handleEditKeyExpiryChange = function() {
  const mode = document.getElementById("edit-key-expiry-mode")?.value;
  const daysWrapper = document.getElementById("edit-key-days-wrapper");
  if (daysWrapper) {
    daysWrapper.style.display = mode === "extend" ? "block" : "none";
  }
};

async function loadApiKeys() {
  const tbody = document.getElementById("keys-table-body");
  if (!tbody) return;

  tbody.innerHTML = UI.stateRow(7, "loading", "Loading API keys...");

  try {
    const keys = await API.request("/api/keys");
    if (!keys || keys.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7">
            ${UI.emptyStateHTML("key", "No API Keys Yet", "Click \"Generate API Key\" above to create your first secret key.")}
          </td>
        </tr>`;
      return;
    }

    tbody.innerHTML = keys
      .map((k) => {
        const statusBadge = k.is_active
          ? UI.badge("Active", "emerald")
          : UI.badge("Disabled", "rose");
        const lastUsed = k.last_used_at ? UI.formatDate(k.last_used_at) : '<span class="cell-muted">Never</span>';
        const created = k.created_at ? UI.formatDate(k.created_at) : "-";
        const expires = k.expires_at ? UI.formatDate(k.expires_at) : '<span class="cell-muted">Permanent</span>';

        return `
          <tr>
            <td data-label="Key Label"><span class="cell-strong">${UI.escapeHtml(k.name)}</span></td>
            <td data-label="Prefix">
              <button class="code-pill" onclick="revealAndCopyApiKey(${k.id})" title="Copy full API key">
                ${icon("copy", 13)}<span>${UI.escapeHtml(k.prefix)}</span>
              </button>
            </td>
            <td data-label="Status">${statusBadge}</td>
            <td data-label="Last Used"><span class="cell-date">${lastUsed}</span></td>
            <td data-label="Created"><span class="cell-date">${created}</span></td>
            <td data-label="Expires"><span class="cell-date">${expires}</span></td>
            <td data-label="Actions" class="table-actions-cell">
              <div class="table-actions">
                <button
                  class="btn btn-secondary btn-sm"
                  onclick="openEditApiKeyModal(${k.id}, '${UI.escapeHtml(k.name)}', '${UI.escapeHtml(k.prefix)}', ${k.is_active}, '${k.expires_at || ''}')"
                  title="Edit Key"
                >
                  ${icon("edit", 13)} Edit
                </button>
                <button
                  class="btn ${k.is_active ? "btn-secondary" : "btn-primary"} btn-sm"
                  onclick="toggleApiKey(${k.id})"
                  title="${k.is_active ? "Disable Key" : "Enable Key"}"
                >
                  ${k.is_active ? "Disable" : "Enable"}
                </button>
                <button
                  class="btn btn-danger btn-sm"
                  onclick="deleteApiKey(${k.id})"
                  title="Revoke &amp; Delete"
                >
                  ${icon("trash-2", 14)}
                </button>
              </div>
            </td>
          </tr>
        `;
      }).join("");
    } catch (err) {
      tbody.innerHTML = UI.stateRow(7, "error", `Failed to load API keys: ${err.message}`);
    }
  }

async function revealAndCopyApiKey(keyId) {
  try {
    const res = await API.request(`/api/keys/${keyId}/reveal`);
    copyToClipboard(res.api_key, "API Key (full secret)");
  } catch (err) {
    Toast.show(err.message || "Failed to copy API key", "error");
  }
}

async function toggleApiKey(keyId) {
  try {
    const res = await API.request(`/api/keys/${keyId}/toggle`, { method: "PATCH" });
    Toast.show(`API Key ${res.is_active ? "enabled" : "disabled"}`, "info");
    loadApiKeys();
  } catch (err) {
    Toast.show(err.message || "Failed to toggle key", "error");
  }
}

async function deleteApiKey(keyId) {
  const ok = await UI.confirm({
    title: "Revoke API Key?",
    message: "Any script or application using this API key will lose access immediately. This action cannot be undone.",
    confirmText: "Revoke Key",
  });
  if (!ok) return;

  try {
    await API.request(`/api/keys/${keyId}`, { method: "DELETE" });
    Toast.show("API Key permanently revoked and deleted", "success");
    loadApiKeys();
  } catch (err) {
    Toast.show(err.message || "Failed to delete API Key", "error");
  }
}


