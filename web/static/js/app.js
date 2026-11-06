(function () {
  "use strict";

  function init() {
    const job = window.MVP_JOB;
    if (!job || !job.id || job.finished) return;

    const statusEl = document.getElementById("job-status");
    const progressEl = document.getElementById("job-progress");
    const logEl = document.getElementById("job-log");
    const errorEl = document.getElementById("job-error");
    const nextEl = document.getElementById("job-next");
    const hintEl = document.getElementById("job-hint");
    let timer = null;

    function render(data) {
      if (statusEl) {
        statusEl.textContent = data.status_label || data.status;
        statusEl.className = "status status-" + data.status;
      }
      if (progressEl) progressEl.textContent = data.progress || "Выполняется…";
      if (logEl) logEl.textContent = data.log || "";
      if (errorEl) {
        errorEl.textContent = data.error || "";
        errorEl.hidden = !data.error;
      }
      if (data.finished) {
        if (timer) window.clearInterval(timer);
        if (hintEl) hintEl.textContent = "задача завершена";
        if (nextEl) {
          nextEl.href = data.next_url || job.nextUrl;
          nextEl.classList.remove("hidden");
        }
      }
    }

    async function poll() {
      try {
        const response = await fetch("/api/jobs/" + encodeURIComponent(job.id) + "/", {
          headers: { "Accept": "application/json" },
          credentials: "same-origin"
        });
        if (!response.ok) return;
        render(await response.json());
      } catch (err) {
        /* сеть может моргнуть — просто попробуем на следующем тике */
      }
    }

    timer = window.setInterval(poll, 2000);
    poll();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
