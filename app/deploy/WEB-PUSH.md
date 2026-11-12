# Optional browser push setup

Web Push is opt-in and is requested only from the signed-in customer's account page.
It uses the browser Push API and VAPID; no SMS, WhatsApp API, paid gateway, Redis,
or paid notification provider is introduced. Browser vendors operate their own push
delivery endpoints; delivery is best-effort and may be unavailable on some browsers.

1. Install the Python requirements (`pywebpush` is included).
2. Generate one VAPID key pair on a trusted machine using the `vapid --gen` command
   provided by the `py-vapid` dependency. Keep the private key secret.
3. Set `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, and `VAPID_CLAIMS_EMAIL` in the
   deployment environment. Never put the private key in JavaScript or a public file.
4. Deploy over HTTPS. The account page then displays Enable notifications.
5. Customers can turn notifications off from the same account card.

Push is disabled safely when the keys are absent. The public-key endpoint exposes
only the public VAPID key. Order status and back-in-stock in-app notifications are
also sent as browser pushes only to customers with an enabled subscription.
Invalid/expired browser endpoints (HTTP 404/410) are disabled automatically.
