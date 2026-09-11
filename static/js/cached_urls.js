/**
 * 30-Min Cached Download URLs Management Page Logic
 * Uses: icons.js (icon), ui.js (UI), api.js (API, Toast, copyToClipboard)
 */

let currentCachedUrlsPage = 1;
let searchDebounceTimer = null;

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
  loadCachedSummary();
  loadCachedUrls(1);
});

function setupEventListeners() {
  const searchInput = document.getElementById("cached-search-input");
  const sourceFilter = document.getElementById("cached-source-filter");
  const statusFilter = document.getElementById("cached-status-filter");
  const limitSelect = document.getElementById("cached-limit-select");

  if (searchInput) {
    searchInput.addEventListener("input", () => {
      clearTimeout(searchDebounceTimer);
      searchDebounceTimer = setTimeout(() => {
        loadCachedUrls(1);
      }, 300);
    });
  }

  if (sourceFilter) {
    sourceFilter.addEventListener("change", () => loadCachedUrls(1));
  }

  if (statusFilter) {
    statusFilter.addEventListener("change", () => loadCachedUrls(1));
  }

  if (limitSelect) {
    limitSelect.addEventListener("change", () => loadCachedUrls(1));
  }
}

async function loadCachedSummary() {
  try {
    const stats = await API.request("/api/media/stats");
    const activeEl = document.getElementById("summary-active-cached");
    if (activeEl) {
      activeEl.textContent = stats.cached_download_urls || 0;
    }
  } catch (err) {
    console.warn("Failed to load cached summary stats", err);
  }
}

async function loadCachedUrls(page = 1) {
  currentCachedUrlsPage = page;
  const tbody = document.getElementById("cached-urls-tbody");
  const pageInfo = document.getElementById("cached-page-info");
  const paginationControls = document.getElementById("cached-pagination");
  const totalSummaryEl = document.getElementById("summary-total-cached");

  if (!tbody) return;
  tbody.innerHTML = UI.stateRow(7, "loading", "Loading cached download URLs…");

  const search = document.getElementById("cached-search-input")?.value.trim() || "";
  const source = document.getElementById("cached-source-filter")?.value || "all";
  const status = document.getElementById("cached-status-filter")?.value || "all";
  const limit = parseInt(document.getElementById("cached-limit-select")?.value || "10", 10);

  const params = new URLSearchParams({
    page: String(page),
    limit: String(limit),
  });
  if (search) params.set("search", search);
  if (source && source !== "all") params.set("source", source);
  if (status && status !== "all") params.set("status", status);

  try {
    const res = await API.request(`/api/media/cached-urls?${params.toString()}`);

    if (totalSummaryEl && (!search && source === "all" && status === "all")) {
      totalSummaryEl.textContent = res.total || 0;
    }

    if (!res.items || res.items.length === 0) {
      tbody.innerHTML = UI.stateRow(7, "empty", "No cached download URLs match your criteria.");
      if (pageInfo) pageInfo.textContent = "Showing 0 items";
      if (paginationControls) paginationControls.innerHTML = "";
      return;
    }

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

        const sourceTone = item.source === "google_drive" ? "emerald" : "sky";
        const sourceBadge = UI.badge(item.source || "unknown", sourceTone);
        const created = item.created_at ? UI.formatDate(item.created_at) : "-";
        const dedup = item.dedup_key
          ? UI.codePill(item.dedup_key, "Dedup Key", 12)
          : '<span class="cell-muted">—</span>';

        return `
          <tr>
            <td data-label="Media Key">${UI.codePill(item.media_key, "Media Key", 16)}</td>
            <td data-label="Dedup Key">${dedup}</td>
            <td data-label="Source">${sourceBadge}</td>
            <td data-label="Created"><span class="cell-date">${created}</span></td>
            <td data-label="Expires In">${expiryBadge}</td>
            <td data-label="Download URL">
              ${UI.codePill(item.download_url, "Download URL", 24)}
            </td>
            <td data-label="Actions" class="cached-actions-cell">
              <div class="cached-btn-group">
                <button
                  type="button"
                  class="btn btn-secondary btn-sm"
                  data-copy="${UI.escapeHtml(item.download_url)}"
                  data-copy-label="Download URL"
                  title="Copy Direct URL"
                >
                  ${icon("copy", 13)}
                </button>
                <a
                  href="${UI.escapeHtml(item.download_url)}"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="btn btn-secondary btn-sm"
                  title="Open direct streaming URL in new tab"
                >
                  ${icon("link-2", 13)}
                </a>
                <button
                  type="button"
                  class="btn btn-danger btn-sm"
                  onclick="deleteCachedUrl('${UI.escapeHtml(item.media_key)}')"
                  title="Evict this cached entry"
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
      pageInfo.textContent = `Showing ${start}–${end} of ${res.total} cached items (Page ${res.page} of ${res.totalPages})`;
    }

    if (paginationControls) {
      UI.renderPagination(paginationControls, res, (p) => loadCachedUrls(p));
    }
  } catch (err) {
    tbody.innerHTML = UI.stateRow(7, "error", `Failed to load cached URLs: ${err.message}`);
    if (pageInfo) pageInfo.textContent = "Error loading data";
    if (paginationControls) paginationControls.innerHTML = "";
  }
}

async function deleteCachedUrl(mediaKey) {
  const ok = await UI.confirm({
    title: "Evict Cached URL?",
    message: `Are you sure you want to remove the cached download token for media key "${UI.truncate(mediaKey, 20)}"? A new stream token will be requested on next download.`,
    confirmText: "Evict Entry",
    danger: true,
  });
  if (!ok) return;

  try {
    await API.request(`/api/media/cached-urls/${encodeURIComponent(mediaKey)}`, {
      method: "DELETE",
    });
    Toast.show("Cached entry evicted successfully", "success");
    loadCachedSummary();
    loadCachedUrls(currentCachedUrlsPage);
  } catch (err) {
    Toast.show(err.message || "Failed to evict cached URL", "error");
  }
}

async function purgeExpiredUrls() {
  const ok = await UI.confirm({
    title: "Purge Expired URLs?",
    message: "This will remove all expired cache entries immediately from SQLite WAL storage.",
    confirmText: "Purge All Expired",
    danger: false,
  });
  if (!ok) return;

  try {
    const res = await API.request("/api/media/cached-urls/cleanup", {
      method: "POST",
    });
    Toast.show(res.message || "Expired cached URLs purged", "success");
    loadCachedSummary();
    loadCachedUrls(1);
  } catch (err) {
    Toast.show(err.message || "Failed to purge expired URLs", "error");
  }
}
