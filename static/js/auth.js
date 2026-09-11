/**
 * Authentication Module
 */

document.addEventListener("DOMContentLoaded", () => {
  if (window.location.pathname.includes("/login")) {
    const form = document.getElementById("login-form");
    const errorBox = document.getElementById("auth-error");
    const submitBtn = document.getElementById("login-btn");

    if (form) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const username = form.username.value.trim();
        const password = form.password.value;

        if (!username || !password) {
          showAuthError("Please enter both username and password.");
          return;
        }

        const reset = UI.setBusy(submitBtn, "Authenticating...");
        hideAuthError();

        try {
          const res = await API.request("/api/auth/login", {
            method: "POST",
            body: { username, password },
          });

          API.setToken(res.access_token, res.username, res.expires_timestamp);
          Toast.show("Login successful! Redirecting...", "success");
          setTimeout(() => {
            window.location.href = "/";
          }, 600);
        } catch (err) {
          showAuthError(err.message || "Invalid username or password");
          reset();
        }
      });
    }
  }
});

function showAuthError(msg) {
  const box = document.getElementById("auth-error");
  if (box) {
    box.textContent = msg;
    box.style.display = "block";
  }
}

function hideAuthError() {
  const box = document.getElementById("auth-error");
  if (box) {
    box.style.display = "none";
  }
}

async function logout() {
  try {
    await API.request("/api/auth/logout", { method: "POST" });
  } catch (e) {}
  API.clearAuth();
  document.cookie = "access_token=; path=/; max-age=0; SameSite=Lax";
  window.location.replace("/login");
}
