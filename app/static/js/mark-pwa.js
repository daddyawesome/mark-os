(() => {
  "use strict";
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register("/service-worker.js"));
  }

  const form = document.querySelector("[data-offline-checkin]");
  if (!form) return;
  const storageKey = "mark-os-offline-checkin-v1";
  const status = form.querySelector("[data-offline-checkin-status]");
  const requestKey = form.querySelector("[data-checkin-request-key]");
  const showStatus = (message) => {
    status.textContent = message;
    status.classList.remove("is-hidden");
  };
  const ensureKey = () => {
    if (!requestKey.value) requestKey.value = crypto.randomUUID();
  };
  const saveDraft = () => {
    ensureKey();
    const values = Object.fromEntries(new FormData(form).entries());
    localStorage.setItem(storageKey, JSON.stringify(values));
  };

  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || "null");
    if (saved) {
      Object.entries(saved).forEach(([name, value]) => {
        const field = form.elements.namedItem(name);
        if (field && typeof value === "string") field.value = value;
      });
      showStatus(navigator.onLine ? "Offline draft restored. Review it, then submit." : "Offline draft saved in this browser. Reconnect to submit.");
    }
  } catch (_) {
    localStorage.removeItem(storageKey);
  }
  ensureKey();
  form.addEventListener("input", saveDraft);
  form.addEventListener("submit", (event) => {
    ensureKey();
    if (!navigator.onLine) {
      event.preventDefault();
      event.stopImmediatePropagation();
      saveDraft();
      showStatus("Offline draft saved in this browser. Reconnect, review, and submit again.");
    }
  }, true);
  document.body.addEventListener("htmx:afterRequest", (event) => {
    if (event.detail.elt === form && event.detail.successful) {
      localStorage.removeItem(storageKey);
      requestKey.value = crypto.randomUUID();
      status.classList.add("is-hidden");
    }
  });
  window.addEventListener("online", () => showStatus("Back online. Review the draft, then submit."));
})();
