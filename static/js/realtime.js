(() => {
  "use strict";

  function afficherNotification(message) {
    const zone = document.querySelector(".realtime-toast-zone") || document.body.appendChild(
      Object.assign(document.createElement("div"), {
        className: "toast-container position-fixed top-0 end-0 p-3 realtime-toast-zone",
      })
    );
    const toast = document.createElement("div");
    toast.className = "toast border-0 shadow";
    toast.setAttribute("role", "status");
    toast.innerHTML = `
      <div class="toast-header">
        <i class="bi bi-bell-fill text-danger me-2"></i>
        <strong class="me-auto"></strong>
        <button type="button" class="btn-close" data-bs-dismiss="toast" aria-label="Fermer"></button>
      </div>
      <div class="toast-body"></div>`;
    toast.querySelector("strong").textContent = message.data.titre;
    toast.querySelector(".toast-body").textContent = message.data.message;
    if (message.data.lien) {
      toast.addEventListener("click", (event) => {
        if (!event.target.closest("button")) window.location.assign(message.data.lien);
      });
      toast.classList.add("realtime-toast-clickable");
    }
    zone.appendChild(toast);
    toast.addEventListener("hidden.bs.toast", () => toast.remove());
    bootstrap.Toast.getOrCreateInstance(toast, { delay: 8000 }).show();

    if ("Notification" in window && Notification.permission === "granted") {
      const notification = new Notification(message.data.titre, { body: message.data.message });
      notification.onclick = () => {
        window.focus();
        if (message.data.lien) window.location.assign(message.data.lien);
      };
    }
  }

  function connecter() {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${scheme}://${window.location.host}/ws/realtime/`);

    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        window.dispatchEvent(new CustomEvent("maintenance-event", { detail: message }));

        // Mise à jour du badge de notifications
        const badge = document.querySelector(".notif-badge");
        if (badge) {
          const count = parseInt(badge.textContent, 10) || 0;
          badge.textContent = count + 1;
          badge.classList.remove("d-none");
        }

        afficherNotification(message);

        if (message.type === "panne_creee") {
          const card = document.querySelector("[data-open-incidents-card]");
          const icon = document.querySelector("[data-open-incidents-icon]");
          const count = document.querySelector("[data-open-incidents-count]");
          card?.classList.add("metric-card-alerting");
          icon?.classList.replace("bi-exclamation-diamond", "bi-bell-fill");
          if (count) count.textContent = (parseInt(count.textContent, 10) || 0) + 1;
        }
      } catch (e) {
        console.warn("Événement WS non parsable :", e);
      }
    };

    socket.onclose = () => {
      // Reconnexion automatique après 5 secondes
      setTimeout(connecter, 5000);
    };

    socket.onerror = (err) => {
      console.warn("WebSocket erreur :", err);
    };
  }

  // Ne connecter que si l'utilisateur est authentifié (balise présente)
  if (document.querySelector("[data-ws-enabled]")) {
    connecter();
  }
})();
