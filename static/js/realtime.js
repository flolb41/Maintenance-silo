(() => {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(
    `${scheme}://${window.location.host}/ws/realtime/`
  );

  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);

    window.dispatchEvent(
      new CustomEvent("maintenance-event", {
        detail: message,
      })
    );

    console.log("Événement temps réel :", message);
  };

  socket.onclose = () => {
    console.warn("Connexion temps réel fermée.");
  };
})();
