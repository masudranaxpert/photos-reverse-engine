/**
 * API Client & Shared Utilities
 */

const API = {
  getToken() {
    return localStorage.getItem("photos_engine_token") || localStorage.getItem("auth_token");
  },

  setToken(token, username, expiresTimestamp) {
    localStorage.setItem("photos_engine_token", token);
    localStorage.setItem("auth_token", token);
    if (username) {
      localStorage.setItem("photos_engine_user", username);
    }
    if (expiresTimestamp) {
      localStorage.setItem("photos_engine_token_exp", String(expiresTimestamp));
    }
    const maxAge = expiresTimestamp ? 86400 * 7 : 86400;
    document.cookie = `access_token=${encodeURIComponent(token)}; path=/; max-age=${maxAge}; SameSite=Lax`;
  },

  getUsername() {
    return localStorage.getItem("photos_engine_user") || "Admin";
  },

  clearAuth() {
    localStorage.removeItem("photos_engine_token");
    localStorage.removeItem("auth_token");
    localStorage.removeItem("photos_engine_user");
    localStorage.removeItem("photos_engine_token_exp");
    document.cookie = "access_token=; path=/; max-age=0; SameSite=Lax";
  },

  isAuthenticated() {
    const token = this.getToken();
    if (!token) return false;
    const exp = localStorage.getItem("photos_engine_token_exp");
    if (exp && Math.floor(Date.now() / 1000) >= parseInt(exp, 10)) {
      this.clearAuth();
      return false;
    }
    return true;
  },

  async request(endpoint, options = {}) {
    const url = endpoint.startsWith("http") ? endpoint : endpoint;
    const headers = options.headers || {};

    const token = this.getToken();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    if (options.body && !(options.body instanceof FormData)) {
      if (typeof options.body === "object") {
        options.body = JSON.stringify(options.body);
      }
      if (!headers["Content-Type"]) {
        headers["Content-Type"] = "application/json";
      }
    }

    options.headers = headers;

    try {
      const response = await fetch(url, options);
      const data = await response.json().catch(() => ({}));

      if (response.status === 401) {
        const onLoginPage = window.location.pathname.includes("/login");
        if (!onLoginPage) {
          this.clearAuth();
          window.location.href = "/login";
          throw new Error(data.detail || "Session expired. Please log in again.");
        }
        throw new Error(data.detail || "Invalid username or password");
      }

      if (!response.ok) {
        let msg = data.message;
        if (typeof data.detail === "string") {
          msg = data.detail;
        } else if (Array.isArray(data.detail)) {
          msg = data.detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
        } else if (data.detail && typeof data.detail === "object") {
          msg = JSON.stringify(data.detail);
        }
        throw new Error(msg || `Request failed with status ${response.status}`);
      }

      return data;
    } catch (error) {
      throw error;
    }
  }
};

/**
 * Global Toast Notification Helper
 */
const Toast = {
  ICONS: { success: "check", error: "circle-alert", info: "info" },

  show(message, type = "info", duration = 3500) {
    let container = document.getElementById("toast-container");
    if (!container) {
      container = document.createElement("div");
      container.id = "toast-container";
      document.body.appendChild(container);
    }

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.innerHTML =
      `<span class="toast-icon">${icon(this.ICONS[type] || "info", 17)}</span>` +
      `<span class="toast-message">${UI.escapeHtml(message)}</span>`;
    container.appendChild(toast);

    requestAnimationFrame(() => toast.classList.add("visible"));

    setTimeout(() => {
      toast.classList.remove("visible");
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }
};

/**
 * Clipboard Helper
 */
function copyToClipboard(text, label = "Item") {
  if (!text) return;
  navigator.clipboard.writeText(text).then(() => {
    Toast.show(`${label} copied to clipboard!`, "success", 2000);
  }).catch(() => {
    Toast.show("Failed to copy", "error");
  });
}
