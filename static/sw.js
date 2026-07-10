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
