(function () {
  "use strict";
  const enable = document.getElementById("enable-push");
  const disable = document.getElementById("disable-push");
  const status = document.getElementById("push-status");
  if (!enable || !disable || !status) return;
  const csrf = enable.dataset.csrf;
  const say = (message) => { status.textContent = message; };
  const b64 = (value) => {
    const pad = "=".repeat((4 - value.length % 4) % 4);
    const raw = atob((value + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, c => c.charCodeAt(0));
  };
  async function post(url, payload) {
    const response = await fetch(url, {method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRFToken": csrf},
      body: JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.message || "Request failed.");
    return result;
  }
  enable.addEventListener("click", async () => {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      say("Push notifications are not supported by this browser."); return;
    }
    if (!window.isSecureContext) { say("Notifications require a secure HTTPS connection."); return; }
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") { say("Permission was not granted."); return; }
      const keyResponse = await fetch("/push/vapid-public-key", {credentials: "same-origin"});
      const keyData = await keyResponse.json();
      if (!keyData.publicKey) { say("Notifications are not configured by the shop yet."); return; }
      const registration = await navigator.serviceWorker.register("/sw.js");
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true, applicationServerKey: b64(keyData.publicKey)
      });
      await post("/account/push/subscribe", {subscription: subscription.toJSON()});
      say("Browser notifications enabled.");
    } catch (error) { say(error.message || "Could not enable notifications."); }
  });
  disable.addEventListener("click", async () => {
    try {
      const registration = await navigator.serviceWorker.getRegistration("/");
      const subscription = registration && await registration.pushManager.getSubscription();
      if (subscription) {
        await post("/account/push/unsubscribe", {endpoint: subscription.endpoint});
        await subscription.unsubscribe();
      }
      say("Browser notifications disabled.");
    } catch (error) { say(error.message || "Could not disable notifications."); }
  });
}());
