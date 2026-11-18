const MENU_ID = "easy-save-audio-video-copy-url";
const BRIDGE = "http://127.0.0.1:8765";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: MENU_ID,
    title: "Easy Save Audio & Video - 주소복사",
    contexts: ["page", "link", "video"],
    visible: false
  });
});

async function refreshMenuVisibility() {
  let visible = false;
  try {
    const response = await fetch(BRIDGE + "/status", {cache: "no-store"});
    if (response.ok) {
      const state = await response.json();
      visible = state.enabled === true;
    }
  } catch (_) {
    visible = false;
  }
  try {
    await chrome.contextMenus.update(MENU_ID, {visible});
    chrome.contextMenus.refresh();
  } catch (_) {}
}

chrome.contextMenus.onShown.addListener(() => {
  refreshMenuVisibility();
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== MENU_ID) return;
  const url = info.linkUrl || info.pageUrl || (tab && tab.url) || "";
  if (!/^https?:\/\//i.test(url)) return;
  try {
    await fetch(BRIDGE + "/insert", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url})
    });
  } catch (_) {
    // The desktop app may not be running; the next menu opening rechecks its status.
  }
});

chrome.runtime.onStartup.addListener(refreshMenuVisibility);
