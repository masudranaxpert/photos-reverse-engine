/**
 * Reusable UI Helpers
 * -------------------
 * Shared rendering + interaction primitives used by every page:
 *   - Formatters:      escapeHtml, truncate, formatDate
 *   - Fragments:       badge, codePill, stateRow, emptyStateHTML
 *   - Table states:    renderTableState (loading / empty / error)
 *   - Pagination:      renderPagination
 *   - Modals:          Modal.open / Modal.close (auto backdrop + esc)
 *   - Confirm dialog:  UI.confirm({ title, message }) -> Promise<boolean>
 *   - Buttons:         UI.setBusy(btn, label) / UI.resetBusy(btn)
 */

const UI = {
  /* ---------- Formatters ---------- */

  escapeHtml(unsafe) {
    return String(unsafe ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  },

  escapeHTML(unsafe) {
    return this.escapeHtml(unsafe);
  },

  truncate(str, len = 12) {
    if (!str) return "";
    return str.length <= len ? str : str.substring(0, len) + "…";
  },

  formatDate(isoStr) {
    if (!isoStr) return "-";
    try {
      const d = new Date(isoStr);
      return (
        d.toLocaleDateString() +
        " " +
        d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      );
    } catch {
      return isoStr;
    }
  },

  formatTableDate(isoStr) {
    if (!isoStr) return `<span class="text-muted">—</span>`;
    try {
      const d = new Date(isoStr);
      const datePart = d.toLocaleDateString();
      const timePart = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      return (
        `<div class="cell-date">` +
        `<span class="cell-date-day">${this.escapeHtml(datePart)}</span>` +
        `<span class="cell-date-time">${this.escapeHtml(timePart)}</span>` +
        `</div>`
      );
    } catch {
      return `<div class="cell-date"><span>${this.escapeHtml(isoStr)}</span></div>`;
    }
  },

  formatBytes(bytes) {
    if (!bytes || bytes <= 0) return "";
    const units = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
  },

  /* ---------- Fragments ---------- */

  badge(text, tone = "neutral") {
    return `<span class="badge badge-${tone}">${this.escapeHtml(text)}</span>`;
  },

  codePill(value, label, displayLen = 14) {
    if (!value) return `<span class="text-muted">—</span>`;
    const safe = this.escapeHtml(value);
    return (
      `<button type="button" class="code-pill" title="Copy ${this.escapeHtml(label)}" ` +
      `data-copy="${safe}" data-copy-label="${this.escapeHtml(label)}">` +
      `${icon("copy", 13)}<span>${this.escapeHtml(this.truncate(value, displayLen))}</span></button>`
    );
  },

  /**
   * Full-width table cell state (loading spinner / message / error).
   * @param {number} colspan - table column count
   * @param {"loading"|"empty"|"error"} kind
   * @param {string} message
   */
  stateRow(colspan, kind, message) {
    if (kind === "loading") {
      return (
        `<tr><td colspan="${colspan}" class="cell-state">` +
        `<span class="inline-spinner">${icon("loader-circle", 20)}</span> ${this.escapeHtml(message)}` +
        `</td></tr>`
      );
    }
    const tone = kind === "error" ? "text-danger" : "text-muted";
    const iconName = kind === "error" ? "circle-alert" : "inbox";
    return (
      `<tr><td colspan="${colspan}" class="cell-state ${tone}">` +
      `${icon(iconName, 18)} ${this.escapeHtml(message)}</td></tr>`
    );
  },

  /**
   * Rich empty state block (icon + title + hint).
   */
  emptyStateHTML(iconName, title, text) {
    return (
      `<div class="empty-state"><div class="empty-state-icon">${icon(iconName, 30)}</div>` +
      `<div class="empty-state-title">${this.escapeHtml(title)}</div>` +
      `<div class="empty-state-text">${this.escapeHtml(text)}</div></div>`
    );
  },

  /**
   * Render pagination controls into a container.
   * @param {HTMLElement} container
   * @param {{page:number, totalPages:number}} res
   * @param {Function} onPage - callback(page)
   */
  renderPagination(container, res, onPage) {
    if (!container) return;
    const page = Math.max(1, res.page || 1);
    const totalPages = Math.max(1, res.totalPages || res.total_pages || 1);

    const jump = (target, label, iconName, disabled) =>
      `<button class="page-btn page-jump" data-page="${target}" ${disabled ? "disabled" : ""} aria-label="${label}" title="${label}">${icon(iconName, 14)}</button>`;

    let html = "";
    html += jump(1, "First page", "chevrons-left", page <= 1);
    html += jump(page - 1, "Previous page", "chevron-left", page <= 1);

    // Numbered window: 1 … prev [current] next … last
    const nums = [...new Set([1, page - 1, page, page + 1, totalPages])]
      .filter((p) => p >= 1 && p <= totalPages)
      .sort((a, b) => a - b);

    let prev = 0;
    for (const p of nums) {
      if (prev && p - prev > 1) html += `<span class="page-ellipsis">…</span>`;
      html += `<button class="page-btn ${p === page ? "active" : ""}" data-page="${p}" aria-label="Page ${p}">${p}</button>`;
      prev = p;
    }

    html += jump(page + 1, "Next page", "chevron-right", page >= totalPages);
    html += jump(totalPages, "Last page", "chevrons-right", page >= totalPages);

    container.innerHTML = html;
    container.querySelectorAll(".page-btn[data-page]").forEach((b) => {
      b.addEventListener("click", () => {
        const p = parseInt(b.dataset.page, 10);
        if (p >= 1 && p <= totalPages && p !== page) onPage(p);
      });
    });
  },

  /* ---------- Buttons ---------- */

  /**
   * Put a submit button into busy state and return a restore function.
   */
  setBusy(btn, busyLabel) {
    if (!btn) return () => {};
    const original = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<span class="inline-spinner">${icon("loader-circle", 16)}</span> ${this.escapeHtml(busyLabel)}`;
    return () => {
      btn.disabled = false;
      btn.innerHTML = original;
    };
  },

  /* ---------- Modals ---------- */

  /**
   * Wire open/close behavior for a modal pair.
   * @param {string} modalId  - .modal-backdrop element id
   * @param {string} openId   - trigger button id
   * @param {string} closeId  - close button id
   */
  bindModal(modalId, openId, closeId) {
    const modal = document.getElementById(modalId);
    if (!modal) return;
    const open = document.getElementById(openId);
    const close = document.getElementById(closeId);
    if (open) open.addEventListener("click", () => this.openModal(modal));
    if (close) close.addEventListener("click", () => this.closeModal(modal));
    modal.addEventListener("click", (e) => {
      if (e.target === modal) this.closeModal(modal);
    });
  },

  openModal(modal) {
    const el = typeof modal === "string" ? document.getElementById(modal) : modal;
    if (!el) return;
    el.classList.add("open");
    document.body.style.overflow = "hidden";
  },

  closeModal(modal) {
    const el = typeof modal === "string" ? document.getElementById(modal) : modal;
    if (!el) return;
    el.classList.remove("open");
    document.body.style.overflow = "";
  },

  showModal(modal) {
    this.openModal(modal);
  },

  hideModal(modal) {
    this.closeModal(modal);
  },

  /**
   * Promise-based confirmation dialog (replaces window.confirm).
   * Requires a #confirm-dialog markup in the page (see base template include pattern).
   */
  confirm({ title = "Are you sure?", message = "", confirmText = "Confirm", danger = true } = {}) {
    return new Promise((resolve) => {
      const modal = document.getElementById("confirm-dialog");
      if (!modal) {
        resolve(window.confirm(message || title));
        return;
      }
      modal.querySelector("#confirm-title").textContent = title;
      modal.querySelector("#confirm-message").textContent = message;
      const okBtn = modal.querySelector("#confirm-ok");
      const cancelBtn = modal.querySelector("#confirm-cancel");
      okBtn.className = "btn " + (danger ? "btn-danger" : "btn-primary");
      okBtn.textContent = confirmText;

      this.openModal(modal);
      const done = (result) => {
        this.closeModal(modal);
        okBtn.onclick = cancelBtn.onclick = null;
        resolve(result);
      };
      okBtn.onclick = () => done(true);
      cancelBtn.onclick = () => done(false);
    });
  },
};

/* Global click handler: any [data-copy] element copies its value. */
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-copy]");
  if (el) copyToClipboard(el.dataset.copy, el.dataset.copyLabel || "Value");
});

/* Shared formatters kept as globals for backwards-compatible inline use. */
function escapeHtml(unsafe) {
  return UI.escapeHtml(unsafe);
}
function truncate(str, len) {
  return UI.truncate(str, len);
}
function formatDate(isoStr) {
  return UI.formatDate(isoStr);
}
