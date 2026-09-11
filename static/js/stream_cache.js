/**
 * 20-Min Cached Streaming URLs Management Page Logic
 * Uses: icons.js (icon), ui.js (UI), api.js (API, Toast, copyToClipboard)
 */

let currentStreamCachePage = 1;
let searchDebounceTimer = null;
let cachedStreamItems = [];
let activeStreamJsonString = "";

document.addEventListener("DOMContentLoaded", () => {
  if (!API.isAuthenticated()) {
    window.location.href = "/login";
    return;
  }

  const userDisplay = document.getElementById("current-user-display");
  if (userDisplay) {
    userDisplay.textContent = API.getUsername();
  }

  setupEventListeners();
  loadStreamSummary();
  loadStreamCache(1);
});

function setupEventListeners() {
  const searchInput = document.getElementById("stream-search-input");
  const statusFilter = document.getElementById("stream-status-filter");
  const limitSelect = document.getElementById("stream-limit-select");
  const jsonModal = document.getElementById("stream-json-modal");

  if (searchInput) {
    searchInput.addEventListener("input", () => {
      clearTimeout(searchDebounceTimer);
      searchDebounceTimer = setTimeout(() => {
        loadStreamCache(1);
      }, 300);
    });
  }

  if (statusFilter) {
    statusFilter.addEventListener("change", () => loadStreamCache(1));
  }

  if (limitSelect) {
    limitSelect.addEventListener("change", () => loadStreamCache(1));
  }

  if (jsonModal) {
    jsonModal.addEventListener("click", (e) => {
      if (e.target === jsonModal) closeStreamJsonModal();
    });
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeStreamJsonModal();
  });
}

async function loadStreamSummary() {
  try {
    const stats = await API.request("/api/media/stats");
    const activeEl = document.getElementById("summary-active-streams");
    if (activeEl) {
      activeEl.textContent = stats.cached_stream_urls || 0;
    }
  } catch (err) {
    console.warn("Failed to load stream cache summary stats", err);
  }
}

async function loadStreamCache(page = 1) {
  currentStreamCachePage = page;
  const tbody = document.getElementById("stream-cache-tbody");
  const pageInfo = document.getElementById("stream-page-info");
  const paginationControls = document.getElementById("stream-pagination");
  const totalSummaryEl = document.getElementById("summary-total-streams");

  if (!tbody) return;
  tbody.innerHTML = UI.stateRow(7, "loading", "Loading cached stream tracks…");

  const search = document.getElementById("stream-search-input")?.value.trim() || "";
  const status = document.getElementById("stream-status-filter")?.value || "all";
  const limit = parseInt(document.getElementById("stream-limit-select")?.value || "10", 10);

  const params = new URLSearchParams({
    page: String(page),
    limit: String(limit),
  });
  if (search) params.set("search", search);
  if (status && status !== "all") params.set("status", status);

  try {
    const res = await API.request(`/api/media/stream-cache?${params.toString()}`);

    if (totalSummaryEl && (!search && status === "all")) {
      totalSummaryEl.textContent = res.total || 0;
    }

    if (!res.items || res.items.length === 0) {
      tbody.innerHTML = UI.stateRow(7, "empty", "No cached streaming representations match your criteria.");
      if (pageInfo) pageInfo.textContent = "Showing 0 items";
      if (paginationControls) paginationControls.innerHTML = "";
      return;
    }

    cachedStreamItems = res.items || [];
    tbody.innerHTML = res.items
      .map((item) => {
        let expiryBadge;
        if (item.remaining_sec <= 0) {
          expiryBadge = UI.badge("Expired", "rose");
        } else {
          const m = Math.floor(item.remaining_sec / 60);
          const s = item.remaining_sec % 60;
          const tone = m < 5 ? "amber" : "emerald";
          expiryBadge = `<span class="badge badge-${tone}">${icon("clock", 12)} ${m}m ${s}s</span>`;
        }

        const created = item.created_at ? UI.formatDate(item.created_at) : "-";

        let resolutionsHtml = '<span class="cell-muted">—</span>';
        if (item.resolutions && item.resolutions.length > 0) {
          resolutionsHtml = `<div class="stream-badge-row">` +
            item.resolutions.map(r => {
              let cls = "quality-pill";
              if (r.includes("1080")) cls += " fhd";
              else if (r.includes("720")) cls += " hd";
              return `<span class="${cls}">${UI.escapeHtml(r)}</span>`;
            }).join("") +
          `</div>`;
        }

        const audioBadge = item.has_audio
          ? `<span class="badge badge-sky">${icon("volume-2", 12)} Audio</span>`
          : `<span class="cell-muted">No Audio</span>`;

        let fileTokenHtml = '<span class="cell-muted">—</span>';
        if (item.filename || item.token) {
          fileTokenHtml = `
            <div style="display: flex; flex-direction: column; gap: 3px;">
              <span style="font-weight: 600; font-size: 0.82rem;" title="${UI.escapeHtml(item.filename || '')}">${UI.truncate(item.filename || 'Untitled', 25)}</span>
              ${item.token ? `<a href="/player/${item.token}" target="_blank" style="font-size: 0.75rem; color: var(--accent); text-decoration: none;">Token: ${item.token.slice(0, 10)}…</a>` : ''}
            </div>
          `;
        }

        const playBtn = item.token
          ? `
            <a
              href="/player/${item.token}"
              target="_blank"
              rel="noopener noreferrer"
              class="btn btn-secondary btn-sm"
              title="Test video streaming player"
            >
              ${icon("play", 13)}
            </a>
          `
          : "";

        return `
          <tr>
            <td data-label="Media Key">${UI.codePill(item.media_key, "Media Key", 16)}</td>
            <td data-label="File / Token">${fileTokenHtml}</td>
            <td data-label="Resolutions">${resolutionsHtml}</td>
            <td data-label="Audio">${audioBadge}</td>
            <td data-label="Created"><span class="cell-date">${created}</span></td>
            <td data-label="Expires In">${expiryBadge}</td>
            <td data-label="Actions" class="cached-actions-cell">
              <div class="cached-btn-group">
                ${playBtn}
                <button
                  type="button"
                  class="btn btn-secondary btn-sm"
                  onclick="openStreamJson(${item.id})"
                  title="View Stream JSON Payload"
                >
                  ${icon("braces", 14)}
                </button>
                <button
                  type="button"
                  class="btn btn-danger btn-sm"
                  onclick="deleteStreamCache(${item.id}, '${UI.escapeHtml(item.media_key)}')"
                  title="Evict this stream cache entry"
                >
                  ${icon("trash-2", 13)}
                </button>
              </div>
            </td>
          </tr>
        `;
      })
      .join("");

    if (pageInfo) {
      const start = (page - 1) * res.limit + 1;
      const end = Math.min(page * res.limit, res.total);
      pageInfo.textContent = `Showing ${start}–${end} of ${res.total} cached stream items (Page ${res.page} of ${res.totalPages})`;
    }

    if (paginationControls) {
      UI.renderPagination(paginationControls, res, (p) => loadStreamCache(p));
    }
  } catch (err) {
    tbody.innerHTML = UI.stateRow(7, "error", `Failed to load stream cache: ${err.message}`);
    if (pageInfo) pageInfo.textContent = "Error loading data";
    if (paginationControls) paginationControls.innerHTML = "";
  }
}

async function deleteStreamCache(id, mediaKey) {
  const ok = await UI.confirm({
    title: "Evict Stream Cache?",
    message: `Are you sure you want to remove the cached streaming tracks for media key "${UI.truncate(mediaKey, 20)}"? A new DASH manifest will be fetched on next visit.`,
    confirmText: "Evict Entry",
    danger: true,
  });
  if (!ok) return;

  try {
    await API.request(`/api/media/stream-cache/${id}`, {
      method: "DELETE",
    });
    Toast.show("Stream cache evicted successfully", "success");
    loadStreamSummary();
    loadStreamCache(currentStreamCachePage);
  } catch (err) {
    Toast.show(err.message || "Failed to evict stream cache", "error");
  }
}

async function purgeExpiredStreams() {
  const ok = await UI.confirm({
    title: "Purge Expired Streams?",
    message: "This will remove all expired stream cache records immediately from SQLite storage.",
    confirmText: "Purge All Expired",
    danger: false,
  });
  if (!ok) return;

  try {
    const res = await API.request("/api/media/stream-cache/cleanup", {
      method: "POST",
    });
    Toast.show(res.message || "Expired stream cache records purged", "success");
    loadStreamSummary();
    loadStreamCache(1);
  } catch (err) {
    Toast.show(err.message || "Failed to purge expired streams", "error");
  }
}

/**
 * Syntax highlight JSON string with colors for keys, strings, numbers, booleans, and nulls.
 */
function syntaxHighlightJson(json) {
  if (typeof json !== "string") {
    json = JSON.stringify(json, null, 2);
  }
  // Sanitize HTML entities
  json = json.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return json.replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
    (match) => {
      let cls = "json-number";
      if (/^"/.test(match)) {
        if (/:$/.test(match)) {
          cls = "json-key";
        } else {
          cls = "json-string";
        }
      } else if (/true|false/.test(match)) {
        cls = "json-boolean";
      } else if (/null/.test(match)) {
        cls = "json-null";
      }
      return `<span class="${cls}">${match}</span>`;
    }
  );
}

function openStreamJson(id) {
  const item = cachedStreamItems.find((x) => x.id === id);
  if (!item) return;

  const titleEl = document.getElementById("stream-json-modal-title");
  const subtitleEl = document.getElementById("stream-json-modal-subtitle");
  const codeEl = document.getElementById("stream-json-code");

  if (titleEl) {
    titleEl.textContent = item.filename || "Cached Stream JSON";
  }
  if (subtitleEl) {
    subtitleEl.textContent = `Media Key: ${item.media_key} • ID #${item.id}`;
  }

  activeStreamJsonString = JSON.stringify(item, null, 2);
  if (codeEl) {
    codeEl.innerHTML = syntaxHighlightJson(item);
  }

  UI.openModal("stream-json-modal");
  if (window.hydrateIcons) window.hydrateIcons(document.getElementById("stream-json-modal"));
}

function closeStreamJsonModal() {
  UI.closeModal("stream-json-modal");
}

async function copyStreamJsonContent() {
  if (!activeStreamJsonString) return;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(activeStreamJsonString);
    } else {
      const ta = document.createElement("textarea");
      ta.value = activeStreamJsonString;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    Toast.show("JSON copied to clipboard", "success");
  } catch (err) {
    Toast.show("Failed to copy JSON", "error");
  }
}

window.openStreamJson = openStreamJson;
window.closeStreamJsonModal = closeStreamJsonModal;
window.copyStreamJsonContent = copyStreamJsonContent;
