/**
 * Audit Log Page Logic
 * Uses: icons.js (icon), ui.js (UI), api.js (API, Toast)
 */

const AUDIT_PAGE_SIZE = 50;
let auditCurrentPage = 1;

const AUDIT_LEVEL_META = {
  critical: { label: "Critical", icon: "circle-alert" },
  error: { label: "Error", icon: "circle-alert" },
  warning: { label: "Warning", icon: "circle-alert" },
  info: { label: "Info", icon: "info" },
};

function auditLevelBadge(level) {
  const meta = AUDIT_LEVEL_META[level] || AUDIT_LEVEL_META.warning;
  const safeLevel = UI.escapeHtml(level);
  return (
    `<span class="audit-level-badge lb-${safeLevel}" title="${safeLevel}">` +
    `${icon(meta.icon, 12)} ${UI.escapeHtml(meta.label)}</span>`
  );
}

function auditStatusBadge(isActive) {
  return isActive
    ? `<span class="audit-status-badge st-active"><span class="dot"></span>Active</span>`
    : `<span class="audit-status-badge st-dismissed"><span class="dot"></span>Dismissed</span>`;
}

function auditTruncateMessage(message) {
  if (!message || message.length <= 140) return UI.escapeHtml(message || "");
  return `<span title="${UI.escapeHtml(message)}">${UI.escapeHtml(message.slice(0, 137))}…</span>`;
}

function auditSourceAction(n) {
  if (n.source === "quota") {
    return (
      `<button class="btn btn-danger btn-sm" onclick="resetQuotaFromAudit()" ` +
      `title="Wipe Google Photos library &amp; empty trash to recover quota">` +
      `${icon("trash-2", 13)} Reset &amp; Free Space</button>`
    );
  }
  if (n.source === "cookies" && n.is_active) {
    return (
      `<button class="btn btn-secondary btn-sm" onclick="window.location.href='/'" ` +
      `title="Open Cookie Sessions on the dashboard">${icon("cookie", 13)} Update Cookies</button>`
    );
  }
  return "";
}

async function loadAudit(page = 1) {
  const tbody = document.getElementById("audit-tbody");
  const infoEl = document.getElementById("audit-page-info");
  const pagerEl = document.getElementById("audit-pagination");
  if (!tbody) return;

  const status = document.getElementById("audit-status-filter").value || "all";
  auditCurrentPage = page;

  try {
    tbody.innerHTML = UI.stateRow(6, "loading", "Loading audit log…");
    const res = await API.request(
      `/api/notices/paginated?page=${page}&page_size=${AUDIT_PAGE_SIZE}&status=${status}`
    );
    const notices = res.notices || [];

    if (notices.length === 0) {
      tbody.innerHTML = UI.stateRow(6, "empty", "No audit entries yet — system events will appear here.");
      infoEl.textContent = "Showing 0 entries";
      pagerEl.innerHTML = "";
      return;
    }

    tbody.innerHTML = notices.map((n) => {
      const level = n.level || "warning";
      const dismissBtn = n.is_active
        ? `<button class="audit-dismiss-btn" onclick="dismissAuditRow(${n.id})" title="Dismiss entry">` +
          `${icon("x", 14)}</button>`
        : "";
      return `
        <tr>
          <td>${auditLevelBadge(level)}</td>
          <td>
            <div class="audit-event-title">${UI.escapeHtml(n.title)}</div>
            <div class="audit-event-message">${auditTruncateMessage(n.message)}</div>
          </td>
          <td><span class="audit-source-chip">${UI.escapeHtml(n.source)}</span></td>
          <td>${auditStatusBadge(n.is_active)}</td>
          <td class="audit-time">${UI.formatDate(n.updated_at || n.created_at)}</td>
          <td class="audit-actions-cell">
            <div class="audit-btn-group">
              ${n.is_active ? auditSourceAction(n) : ""}
              ${dismissBtn}
            </div>
          </td>
        </tr>
      `;
    }).join("");

    const from = (res.page - 1) * res.page_size + 1;
    const to = Math.min(res.page * res.page_size, res.total);
    infoEl.textContent = `Showing ${from}–${to} of ${res.total} entries (Page ${res.page} of ${res.total_pages})`;
    UI.renderPagination(pagerEl, { page: res.page, totalPages: res.total_pages }, loadAudit);
  } catch (err) {
    tbody.innerHTML = UI.stateRow(6, "error", "Failed to load audit log.");
    console.warn("Failed to load audit log", err);
  }
}

async function dismissAuditRow(id) {
  try {
    await API.request(`/api/notices/${id}/dismiss`, { method: "POST" });
    Toast.show("Entry dismissed", "info");
    loadAudit(auditCurrentPage);
  } catch (err) {
    Toast.show(`Failed to dismiss: ${err.message}`, "error");
  }
}

async function dismissAllAudit() {
  const ok = await UI.confirm({
    title: "Dismiss All Alerts?",
    message: "Every active alert will be marked as dismissed in the audit log. This cannot be undone.",
    confirmText: "Dismiss All",
    danger: true,
  });
  if (!ok) return;
  try {
    const res = await API.request("/api/notices/clear", { method: "POST" });
    Toast.show(res.message || "All alerts dismissed", "success");
    loadAudit(1);
  } catch (err) {
    Toast.show(`Failed to dismiss: ${err.message}`, "error");
  }
}

async function resetQuotaFromAudit() {
  const ok = await UI.confirm({
    title: "Reset Google Photos Account?",
    message: "This will permanently wipe your Google Photos library and empty the trash to recover storage quota. All items currently in Google Photos will be removed.",
    confirmText: "Wipe & Free Space",
    danger: true,
  });
  if (!ok) return;
  try {
    Toast.show("Wiping Google Photos library and emptying trash...", "info");
    const res = await API.request("/api/web/reset-account", {
      method: "POST",
      body: { confirm: true },
    });
    showResetResult(res);
    loadAudit(auditCurrentPage);
  } catch (err) {
    Toast.show(`Account reset failed: ${err.message}`, "error");
  }
}

function showResetResult(res) {
  const titleEl = document.getElementById("reset-result-title");
  const bodyEl = document.getElementById("reset-result-body");
  if (!bodyEl) return;
  const ok = !!res.success;
  if (titleEl) titleEl.textContent = ok ? "Reset Complete" : "Reset Finished With Issues";

  const deleted = (res.total_deleted === undefined || res.total_deleted === null) ? "—" : res.total_deleted;
  bodyEl.innerHTML = `
    <div class="reset-result-stats">
      <div class="reset-stat">
        <div class="reset-stat-value">${UI.escapeHtml(String(deleted))}</div>
        <div class="reset-stat-label">Items Deleted</div>
      </div>
      <div class="reset-stat ${res.trash_emptied ? "stat-ok" : "stat-muted"}">
        <div class="reset-stat-value">${res.trash_emptied ? "Yes" : "No"}</div>
        <div class="reset-stat-label">Trash Emptied</div>
      </div>
    </div>
    <p class="reset-result-message">${UI.escapeHtml(res.message || "No additional details were returned by Google Photos.")}</p>
  `;
  UI.openModal("reset-result-modal");
}

document.addEventListener("DOMContentLoaded", () => {
  loadAudit(1);
  const filter = document.getElementById("audit-status-filter");
  if (filter) filter.addEventListener("change", () => loadAudit(1));
});
