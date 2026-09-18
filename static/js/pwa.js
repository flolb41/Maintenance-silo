(() => {
  const QUEUE_KEY = "maintenance-silo-offline-actions";
  const readQueue = () => JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]");
  const writeQueue = (queue) => localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));

  const showNetworkState = () => {
    let banner = document.querySelector("[data-network-state]");
    if (!banner) {
      banner = document.createElement("div");
      banner.dataset.networkState = "";
      banner.className = "network-state";
      document.body.appendChild(banner);
    }
    const pending = readQueue().length;
    banner.textContent = navigator.onLine
      ? (pending ? `${pending} action(s) en attente de synchronisation` : "En ligne")
      : "Mode hors ligne";
    banner.classList.toggle("is-offline", !navigator.onLine);
    banner.classList.toggle("has-pending", pending > 0);
  };

  const replayQueue = async () => {
    if (!navigator.onLine) return;
    const queue = readQueue();
    const remaining = [];
    for (const action of queue) {
      try {
        const response = await fetch(action.url, {
          method: action.method,
          headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
          credentials: "same-origin",
          body: new URLSearchParams(action.fields),
        });
        if (!response.ok) remaining.push(action);
      } catch (error) {
        remaining.push(action);
      }
    }
    writeQueue(remaining);
    showNetworkState();
  };

  const queueSimpleForm = (form) => {
    if (navigator.onLine) return false;
    const selectedFile = [...form.querySelectorAll("input[type=file]")]
      .some((input) => input.files && input.files.length > 0);
    if (selectedFile) return false;
    const fields = {};
    for (const element of form.elements) {
      if (!element.name || element.type === "file" || element.type === "submit") continue;
      if ((element.type === "checkbox" || element.type === "radio") && !element.checked) continue;
      fields[element.name] = element.value;
    }
    const queue = readQueue();
    queue.push({ url: form.action || window.location.href, method: "POST", fields });
    writeQueue(queue);
    showNetworkState();
    form.reset();
    window.alert("Déclaration enregistrée sur cet appareil. Elle sera synchronisée au retour du réseau.");
    return true;
  };

  window.addEventListener("online", replayQueue);
  window.addEventListener("offline", showNetworkState);
  document.addEventListener("submit", (event) => {
    if (event.target.matches("[data-offline-queue]")) {
      if (queueSimpleForm(event.target)) event.preventDefault();
    }
  });

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register("/static/service-worker.js"));
  }
  showNetworkState();
  replayQueue();
})();
