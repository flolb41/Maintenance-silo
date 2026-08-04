(() => {
  "use strict";

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
  if (document.querySelector("[data-ws-enabled]") || document.querySelector(".navbar-nav")) {
    connecter();
  }
})();
