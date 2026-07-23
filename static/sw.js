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

// ── 푸시 알림 수신 ──
self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) {}
  const title = data.title || "배송관리 알림";
  const tasks = [
    self.registration.showNotification(title, {
      body: data.body || "",
      icon: "/static/icon-192.png",
      badge: "/static/icon-192.png",
      data: { url: data.url || "/" },
    }),
  ];
  // 앱 아이콘에 숫자 뱃지 표시 (지원 기기: 설치된 iOS 웹앱 등)
  if (data.badge && "setAppBadge" in navigator) {
    tasks.push(navigator.setAppBadge(data.badge).catch(() => {}));
  }
  event.waitUntil(Promise.all(tasks));
});

// 알림 클릭 → 앱 열기 (해당 배송카드로 이동)
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      for (const win of wins) {
        if ("focus" in win) {
          win.focus();
          if ("navigate" in win) win.navigate(url);
          return;
        }
      }
      return clients.openWindow(url);
    })
  );
});
