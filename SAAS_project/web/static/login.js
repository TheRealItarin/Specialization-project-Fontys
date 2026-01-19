const form = document.getElementById("login-form");
const errorBox = document.getElementById("error-message");
const button = document.getElementById("login-button");

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    method: options.method || "GET",
    headers: {
      "Content-Type": "application/json",
    },
    credentials: "include",
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || payload.message || "Request failed");
  }
  return response.json();
}

async function checkSession() {
  try {
    await api("/session");
    window.location.replace("/");
  } catch (_) {
    // no existing session
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorBox.textContent = "";
  button.disabled = true;
  try {
    const username = form.username.value.trim();
    const password = form.password.value;
    await api("/login", {
      method: "POST",
      body: { username, password },
    });
    window.location.replace("/");
  } catch (error) {
    errorBox.textContent = error.message;
  } finally {
    button.disabled = false;
    form.password.value = "";
  }
});

checkSession();

