const MENU_ID = "easy-save-audio-video-copy-url";
const BRIDGE = "http://127.0.0.1:8765";

// 우클릭 중 비동기로 표시 여부를 바꾸면 메뉴가 첫 클릭에서 누락될 수 있습니다.
// 메뉴는 항상 등록하고, 주소 전달은 앱 내부 체크 상태로 제어합니다.
function createContextMenu() {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: MENU_ID,
      title: "Easy Save Audio & Video - 주소복사",
      contexts: ["page", "link", "video"]
    });
  });
}

chrome.runtime.onInstalled.addListener(createContextMenu);
chrome.runtime.onStartup.addListener(createContextMenu);

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== MENU_ID) return;
  // 동영상 요소의 실제 미디어 주소는 info.srcUrl에 전달됩니다.
  const url = info.linkUrl || info.srcUrl || info.pageUrl || (tab && tab.url) || "";
  if (!/^https?:\/\//i.test(url)) return;
  try {
    const response = await fetch(BRIDGE + "/insert", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url})
    });
    if (!response.ok) {
      console.info("Easy Save Audio & Video: 앱의 우클릭 메뉴 체크 상태를 확인하세요.");
    }
  } catch (_) {
    // 데스크톱 앱이 실행 중이 아니면 주소를 전달할 수 없습니다.
  }
});
