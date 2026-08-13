// 탱크로리 배송관리 서비스 워커
// 현재 역할: PWA 설치 요건 충족 (요청은 네트워크로 그대로 전달)
// 추후 푸시 알림 수신 처리가 여기에 추가됩니다.

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  // 캐시 없이 항상 네트워크 사용 (업무 데이터 실시간성 유지)
  event.respondWith(fetch(event.request));
});

// 뱃지 = 아직 확인하지 않은(알림창에 남아 있는) 알림 수
async function updateBadge() {
  try {
    const notes = await self.registration.getNotifications();
    if (notes.length > 0) {
      if ("setAppBadge" in navigator) await navigator.setAppBadge(Math.min(notes.length, 99));
    } else if ("clearAppBadge" in navigator) {
      await navigator.clearAppBadge();
    }
  } catch (e) {}
}

// ── 푸시 알림 수신 ──
self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) {}
  const title = data.title || "배송관리 알림";
  const url = data.url || "/";
  const m = String(url).match(/open=(\d+)/);
  const deliveryId = m ? parseInt(m[1]) : null;   // 어느 배송카드의 알림인지 기록
  event.waitUntil((async () => {
    await self.registration.showNotification(title, {
      body: data.body || "",
      icon: "/static/icon-192.png",
      badge: "/static/icon-192.png",
      data: { url, deliveryId },
    });
    await updateBadge();
  })());
});

// ── 푸시 구독이 브라우저에서 갱신·폐기된 경우 자동 재등록 ──
// 안드로이드(FCM)는 구독 주소가 주기적으로 바뀐다. 이때 다시 등록하지 않으면
// 서버의 기기 등록이 만료 처리되어 알림이 조용히 끊긴다.
function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = self.atob(base64);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

self.addEventListener("pushsubscriptionchange", (event) => {
  event.waitUntil((async () => {
    try {
      const res = await fetch("/api/push/public-key");
      const { key } = await res.json();
      const sub = await self.registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key),
      });
      await fetch("/api/push/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subscription: sub.toJSON() }),
      });
    } catch (e) {}
  })());
});

// 알림 클릭 → 앱 열기 (해당 배송카드로 이동)
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil((async () => {
    await updateBadge();
    const wins = await clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const win of wins) {
      if ("focus" in win) {
        await win.focus();
        if ("navigate" in win) await win.navigate(url).catch(() => {});
        return;
      }
    }
    await clients.openWindow(url);
  })());
});
