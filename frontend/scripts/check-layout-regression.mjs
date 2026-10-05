/* global WebSocket, process, URL, fetch, Buffer, console */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { once } from "node:events";
import { setTimeout as delay } from "node:timers/promises";

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const browser = process.env.BROWSER_PATH ?? [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/chromium", "/usr/bin/google-chrome",
].find(existsSync);
assert.ok(browser, "Set BROWSER_PATH to an installed Chromium browser");
const profile = mkdtempSync(join(tmpdir(), "chatagents-layout-"));
const screenshots = mkdtempSync(join(tmpdir(), "chatagents-layout-screenshots-"));
const title = "这是一个需要截断但悬停应该显示完整内容的会话标题";
let lastRun = null;
const server = createServer((request, response) => {
  const path = new URL(request.url, "http://localhost").pathname;
  if (path === '/api/runs' && request.method === 'POST') {
    let body = '';
    request.on('data', (chunk) => { body += chunk; });
    request.on('end', () => {
      lastRun = JSON.parse(body);
      response.setHeader('Content-Type', 'text/event-stream');
      response.end('data: {"type":"RUN_STARTED","runId":"test-run"}\n\ndata: {"type":"RUN_FINISHED"}\n\n');
    });
    return;
  }
  if (path.startsWith("/api/")) {
    response.setHeader("Content-Type", "application/json");
    if (path === "/api/sessions") {
      response.end(JSON.stringify(Array.from({ length: 25 }, (_, i) => ({ id: `session-${i}`, title: `${title} ${i}`, updated_at: "2026-10-03T10:00:00Z", message_count: 4 }))));
    } else if (path === "/api/sessions/test-session") {
      response.end(JSON.stringify({ id: "test-session", title: "对话显示测试", created_at: "2026-10-03T10:00:00Z", updated_at: "2026-10-03T10:00:00Z", messages: Array.from({ length: 8 }, (_, i) => ({ id: `message-${i}`, seq: i, role: i % 2 ? "assistant" : "user", content: [{ type: "text", text: i % 2 ? "可以正常显示。这里保留清晰的正文排版，运行详情按需展开，不打断阅读。\n\n你可以继续提问，或者调整侧栏宽度。" : ["你好，我看看显示", "我们正在对话", "希望页面更简洁", "保留运行详情就好"][i / 2] }] })) }));
    } else if (path === "/api/models/profiles") {
      response.end(JSON.stringify({ profiles: [{ name: 'test-profile', status: 'available', main_model: 'default-model', auxiliary_model: null }], default_profile: 'test-profile' }));
    } else if (path === "/api/models") {
      response.end(JSON.stringify({ models: [{ id: 'default-model', owned_by: 'test' }, { id: 'alternate-model', owned_by: 'test' }] }));
    } else if (path.endsWith("/runs")) response.end("[]");
    else { response.statusCode = 404; response.end("{}"); }
    return;
  }
  const file = path.startsWith("/assets/") ? join(frontend, "dist", path) : join(frontend, "dist/index.html");
  response.setHeader("Content-Type", ({ ".js": "text/javascript", ".css": "text/css" })[extname(file)] ?? "text/html");
  response.end(readFileSync(file));
});
server.listen(0, "127.0.0.1");
await once(server, "listening");
const child = spawn(browser, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--no-first-run", "--no-default-browser-check", "about:blank"], { stdio: "ignore" });
let socket;
try {
  const portFile = join(profile, "DevToolsActivePort");
  for (let i = 0; !existsSync(portFile) && i < 100; i++) await delay(100);
  const port = readFileSync(portFile, "utf8").split("\n")[0];
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(targets.find((target) => target.type === "page").webSocketDebuggerUrl);
  await once(socket, "open");
  let id = 0;
  const pending = new Map();
  let pageException = null;
  socket.addEventListener("message", ({ data }) => {
    const event = JSON.parse(data);
    if (event.method === 'Runtime.exceptionThrown') pageException = event.params.exceptionDetails.exception?.description ?? event.params.exceptionDetails.text;
  });
  socket.addEventListener("message", ({ data }) => {
    const message = JSON.parse(data);
    const entry = pending.get(message.id);
    if (entry) {
      pending.delete(message.id);
      if (message.error) entry.reject(message.error);
      else entry.resolve(message.result);
    }
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const key = ++id;
    pending.set(key, { resolve, reject });
    socket.send(JSON.stringify({ id: key, method, params }));
  });
  await send("Runtime.enable");
  const evaluate = async (expression) => {
    const value = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    assert.equal(value.exceptionDetails, undefined, JSON.stringify(value.exceptionDetails));
    return value.result.value;
  };
  const settle = () => evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))");
  const resize = async (width) => { await send("Emulation.setDeviceMetricsOverride", { width, height: 1000, deviceScaleFactor: 1, mobile: false }); await settle(); };
  await send("Page.enable");
  await resize(1600);
  const url = `http://127.0.0.1:${server.address().port}/s/test-session`;
  await send("Page.navigate", { url });
  for (let i = 0; i < 100; i++) {
    if (await evaluate("document.querySelectorAll('.column-resizer').length === 1 && document.querySelectorAll('.chat-turn').length === 8 && !!document.querySelector('.session-item-title')")) break;
    await delay(100);
  }
  assert.equal(await evaluate("document.querySelector('.session-item-title').title"), `${title} 0`);
  assert.deepEqual(await evaluate("[...document.querySelector('.session-item-actions').querySelectorAll('button')].map(button => ({ label: button.getAttribute('aria-label'), title: button.title, icon: !!button.querySelector('svg'), text: button.textContent.trim() }))"), [
    { label: "重命名会话", title: "改名", icon: true, text: "" },
    { label: "删除会话", title: "删除", icon: true, text: "" },
  ]);
  assert.equal(await evaluate("getComputedStyle(document.querySelector('.session-sidebar')).scrollbarWidth"), "thin");
  const drag = async (selector, delta) => {
    const position = await evaluate(`(() => { const r = document.querySelector('${selector}').getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + 40 }; })()`);
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", ...position });
    await send("Input.dispatchMouseEvent", { type: "mousePressed", ...position, button: "left", clickCount: 1 });
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: position.x + delta, y: position.y, button: "left", buttons: 1 });
    await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: position.x + delta, y: position.y, button: "left", clickCount: 1 });
    await settle();
  };
  const value = (selector) => evaluate(`Number(document.querySelector('${selector}').getAttribute('aria-valuenow'))`);
  await evaluate("Promise.all(document.getAnimations().filter(a => Number.isFinite(a.effect.getComputedTiming().iterations)).map(a => a.finished.catch(() => {})))");
  assert.ok(await evaluate("document.querySelector('.message-scroll').getBoundingClientRect().top < 240"), "Chat should begin near the top, not below a large hero");
  assert.ok(await evaluate("document.querySelector('.composer').getBoundingClientRect().bottom <= innerHeight"), "Empty-state composer should remain in the first viewport");
  assert.deepEqual(await evaluate(`(() => {
    const content = document.querySelector('.chat-thread').getBoundingClientRect();
    const composer = document.querySelector('.composer-dock').getBoundingClientRect();
    return [Math.round(content.left - composer.left), Math.round(content.right - composer.right), Math.round(composer.width)];
  })()`), [0, 0, 840], "message and composer edges should align at desktop width");
  assert.equal(await evaluate("document.querySelector('.inspector-card')"), null);
  await evaluate("document.querySelector('.composer-input').focus()");
  assert.deepEqual(await evaluate("(() => { const input = document.querySelector('.composer-input'); const css = getComputedStyle(input); return { focused: document.activeElement === input, outline: css.outlineStyle, shadow: css.boxShadow, caret: css.caretColor }; })()"), { focused: true, outline: 'none', shadow: 'none', caret: 'rgb(237, 237, 237)' });
  await evaluate("document.querySelector('.composer-input').blur()");
  assert.equal(await evaluate(`(() => {
    const input = document.querySelector('.composer-input');
    const event = new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true, cancelable: true });
    input.dispatchEvent(event);
    return event.defaultPrevented;
  })()`), false, 'IME candidate confirmation must not submit or cancel composition');
  assert.equal(await evaluate("document.body.textContent.includes('SESSION / LIVE SURFACE')"), false);
  const minimalView = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(screenshots, "minimal-chat.png"), Buffer.from(minimalView.data, "base64"));
  await settle();
  const checkIndependentScroll = async () => {
    await evaluate(`(() => {
      const filler = document.createElement('div');
      filler.id = 'scroll-regression-fixture';
      filler.style.height = '2400px';
      document.querySelector('.message-scroll').prepend(filler);
      document.querySelector('.message-scroll').scrollTop = 0;
      document.querySelector('.session-sidebar-scroll').scrollTop = 0;
    })()`);
    const wheel = async (selector, deltaY) => {
      const position = await evaluate(`(() => { const r = document.querySelector('${selector}').getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + Math.min(80, r.height / 2) }; })()`);
      await send("Input.dispatchMouseEvent", { type: "mouseMoved", ...position });
      await send("Input.dispatchMouseEvent", { type: "mouseWheel", ...position, deltaX: 0, deltaY });
      await delay(200);
    };
    const sidebarHeadTop = await evaluate("document.querySelector('.session-sidebar-head').getBoundingClientRect().top");
    const accountTop = await evaluate("document.querySelector('.session-sidebar-account').getBoundingClientRect().top");
    const composerTop = await evaluate("document.querySelector('.composer-dock').getBoundingClientRect().top");
    const headerTop = await evaluate("document.querySelector('.topbar').getBoundingClientRect().top");
    await wheel('.session-sidebar-scroll', 240);
    assert.ok(await evaluate("document.querySelector('.session-sidebar-scroll').scrollTop > 0"));
    assert.equal(await evaluate("document.querySelector('.message-scroll').scrollTop"), 0);
    const leftTop = await evaluate("document.querySelector('.session-sidebar-scroll').scrollTop");
    await wheel('.message-scroll', 240);
    assert.ok(await evaluate("document.querySelector('.message-scroll').scrollTop > 0"));
    assert.equal(await evaluate("document.querySelector('.session-sidebar-scroll').scrollTop"), leftTop);
    assert.equal(await evaluate("document.querySelector('.topbar').getBoundingClientRect().top"), headerTop);
    assert.equal(await evaluate("window.scrollY"), 0);
    const rightTop = await evaluate("document.querySelector('.message-scroll').scrollTop");
    await evaluate("document.querySelector('.session-sidebar-scroll').scrollTop = 100000");
    await wheel('.session-sidebar-scroll', 400);
    assert.equal(await evaluate("document.querySelector('.message-scroll').scrollTop"), rightTop);
    await evaluate("document.querySelector('.message-scroll').scrollTop = 100000");
    await wheel('.message-scroll', 400);
    assert.equal(await evaluate("window.scrollY"), 0);
    assert.equal(await evaluate("document.querySelector('.topbar').getBoundingClientRect().top"), headerTop);
    assert.ok(await evaluate("document.documentElement.scrollHeight <= innerHeight"), JSON.stringify(await evaluate("({ height: innerHeight, scroll: document.documentElement.scrollHeight, boxes: [...document.querySelectorAll('.app-shell,.app-body,.route-stage,.session-page,.session-grid,.conversation-card,.message-scroll,.composer-dock')].map(e => ({class: e.className, height: e.getBoundingClientRect().height, scroll: e.scrollHeight, minHeight: getComputedStyle(e).minHeight, overflow: getComputedStyle(e).overflow})) })")));
    assert.equal(await evaluate("document.querySelector('.composer-dock').getBoundingClientRect().top"), composerTop);
    assert.equal(await evaluate("document.querySelector('.session-sidebar-head').getBoundingClientRect().top"), sidebarHeadTop);
    assert.equal(await evaluate("document.querySelector('.session-sidebar-account').getBoundingClientRect().top"), accountTop);
    assert.equal(await evaluate("document.querySelector('.session-sidebar').scrollTop"), 0);
    assert.equal(await evaluate("document.querySelector('.route-stage').scrollTop"), 0);
    await evaluate("document.querySelector('#scroll-regression-fixture').remove(); document.querySelector('.message-scroll').scrollTop = 0; document.querySelector('.session-sidebar-scroll').scrollTop = 0;");
    await settle();
  };
  await checkIndependentScroll();
  assert.equal(await evaluate("document.querySelector('.account-copy strong').textContent"), 'localhost');
  assert.equal(await evaluate("document.querySelector('.account-copy > span').textContent"), '本地用户');
  assert.equal(await evaluate("document.querySelector('.session-sidebar-label').textContent"), 'session');
  assert.equal(await evaluate("document.querySelector('.session-sidebar-new').textContent.trim()"), '+ 新会话');
  assert.equal(await evaluate("document.querySelector('.session-sidebar-new').getAttribute('aria-label')"), '开始新会话');
  assert.equal(await evaluate("document.querySelectorAll('.session-sidebar-account button').length"), 1);
  assert.equal(await evaluate("document.querySelector('.session-sidebar-account button').getAttribute('aria-label')"), '打开设置');
  const itemPoint = await evaluate("(() => { const r = document.querySelector('.session-item-link').getBoundingClientRect(); return {x:r.x + 20,y:r.y + 12}; })()");
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', ...itemPoint });
  await settle();
  assert.equal(await evaluate("getComputedStyle(document.querySelector('.session-item')).backgroundColor"), 'rgb(41, 41, 41)');
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', ...itemPoint, button: 'left', clickCount: 1 });
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', ...itemPoint, button: 'left', clickCount: 1 });
  await settle();
  assert.equal(await evaluate("getComputedStyle(document.querySelector('.session-item')).backgroundColor"), 'rgba(0, 0, 0, 0)');
  assert.equal(await evaluate("document.querySelector('.session-item-link').getAttribute('aria-current')"), 'page');
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 800, y: 30 });
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', ...itemPoint });
  await settle();
  assert.equal(await evaluate("getComputedStyle(document.querySelector('.session-item')).backgroundColor"), 'rgb(41, 41, 41)');
  await evaluate(`window.history.back()`);
  for (let i = 0; i < 100; i++) {
    if (await evaluate("document.querySelectorAll('.chat-turn').length === 8")) break;
    await delay(100);
  }
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 800, y: 30 });
  const defaultView = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(screenshots, "default-proportions.png"), Buffer.from(defaultView.data, "base64"));
  await drag(".app-body > .column-resizer", 70);
  assert.equal(await value(".app-body > .column-resizer"), 326);
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: "ArrowLeft", code: "ArrowLeft", windowsVirtualKeyCode: 37 });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: "ArrowLeft", code: "ArrowLeft", windowsVirtualKeyCode: 37 });
  await settle();
  assert.equal(await value(".app-body > .column-resizer"), 310);
  assert.equal(await evaluate("localStorage.getItem('chatagents.sessions-width')"), "310");
  await send("Page.reload");
  for (let i = 0; i < 100; i++) {
    if (await evaluate("!!document.querySelector('.composer-input')")) break;
    await delay(100);
  }
  await settle();
  assert.equal(await value(".app-body > .column-resizer"), 310);
  await evaluate("Promise.all(document.getAnimations().filter(a => Number.isFinite(a.effect.getComputedTiming().iterations)).map(a => a.finished.catch(() => {})))");
  await evaluate("window.scrollTo(0, 0)");
  const desktop = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(screenshots, "desktop.png"), Buffer.from(desktop.data, "base64"));
  for (const width of [1100, 800, 760, 390, 320]) {
    await resize(width);
    const overflow = await evaluate("document.documentElement.scrollWidth > innerWidth");
    assert.equal(overflow, false, `Page overflow at ${width}px`);
    assert.deepEqual(await evaluate(`(() => {
      const content = document.querySelector('.chat-thread').getBoundingClientRect();
      const composer = document.querySelector('.composer-dock').getBoundingClientRect();
      return [Math.round(content.left - composer.left), Math.round(content.right - composer.right)];
    })()`), [0, 0], `Message and composer edges at ${width}px`);
    if (width <= 760) assert.equal(await evaluate("getComputedStyle(document.querySelector('.app-body > .column-resizer')).display"), "none");
    if (width === 390) await checkIndependentScroll();
  }
  await settle();
  const minimalMobile = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(screenshots, "minimal-mobile.png"), Buffer.from(minimalMobile.data, "base64"));
  await settle();
  const mobile = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(screenshots, "mobile.png"), Buffer.from(mobile.data, "base64"));
  await resize(1600);
  await settle();
  assert.equal(await evaluate("document.querySelectorAll('.session-grid > .column-resizer').length"), 0);
  await settle();
  assert.equal(await value(".app-body > .column-resizer"), 310);
  await send("Page.addScriptToEvaluateOnNewDocument", { source: "Object.defineProperty(window, 'localStorage', { get() { throw new Error('Storage blocked'); } });" });
  await send("Page.reload");
  for (let i = 0; i < 100; i++) {
    if (await evaluate("!!document.querySelector('.composer-input')")) break;
    await delay(100);
  }
  await settle();
  assert.equal(await value(".app-body > .column-resizer"), 256);
  assert.equal(await evaluate("document.querySelector('.session-heading')"), null);
  assert.equal(await evaluate("document.querySelector('.topbar a[href=\"/evals\"]')"), null);
  assert.ok(await evaluate("!!document.querySelector('.quick-model-trigger')"));
  for (let i = 0; i < 100; i++) {
    if (await evaluate("document.querySelector('.quick-model-trigger')?.textContent.includes('default-model')")) break;
    await delay(100);
  }
  await evaluate("document.querySelector('.quick-model-trigger').click()");
  for (let i = 0; i < 100; i++) {
    if (await evaluate("!![...document.querySelectorAll('.quick-model-option')].find(button => button.textContent === 'alternate-model')")) break;
    await delay(100);
  }
  assert.deepEqual(await evaluate("[...document.querySelectorAll('.quick-model-group-name')].map(node => node.textContent)"), ['test']);
  const modelMenu = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(join(screenshots, 'model-menu.png'), Buffer.from(modelMenu.data, 'base64'));
  await evaluate("[...document.querySelectorAll('.quick-model-option')].find(button => button.textContent === 'alternate-model').click()");
  await settle();
  assert.equal(await evaluate("document.querySelector('.quick-model-trigger').textContent"), 'alternate-model');
  assert.equal(await evaluate("document.querySelector('.quick-model-menu')"), null);
  await evaluate(`(() => { const input = document.querySelector('.composer-input'); const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set; setter.call(input, '下一次运行'); input.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await settle();
  assert.equal(await evaluate("document.querySelector('.composer-input').value"), '下一次运行');
  await evaluate("document.querySelector('.composer button[type=submit]').click()");
  await settle();
  assert.ok(await evaluate("!!document.querySelector('.config-confirmation')"));
  assert.equal(await evaluate("document.querySelector('.quick-model-trigger').textContent"), 'alternate-model');
  await evaluate("document.querySelector('.config-confirmation .settings-done').click()");
  for (let i = 0; i < 100 && !lastRun; i++) await delay(50);
  assert.equal(lastRun?.model_override?.main_model, 'alternate-model', JSON.stringify({ lastRun, confirmation: await evaluate("document.querySelector('.config-confirmation')?.textContent"), messages: await evaluate("document.querySelector('.message-scroll')?.textContent.slice(-180)"), selected: await evaluate("document.querySelector('.quick-model-trigger')?.textContent") }));
  assert.equal(await evaluate("!!document.querySelector('.composer-toolbar')"), true, JSON.stringify({ pageException, page: await evaluate("({url: location.href, body: document.body?.textContent.slice(-500)})") }));
  assert.equal(await evaluate("document.querySelector('.composer-toolbar').textContent.includes('高级选项')"), false);
  const composerBeforeSettings = await evaluate("document.querySelector('.composer').getBoundingClientRect().top");
  await evaluate("document.querySelector('[aria-label=\"打开设置\"]').focus(); document.querySelector('[aria-label=\"打开设置\"]').click()");
  await settle();
  assert.equal(await evaluate("document.activeElement.getAttribute('aria-label')"), '关闭设置');
  await evaluate("document.querySelector('.profile-picker .settings-select-trigger').click()");
  await settle();
  await evaluate("[...document.querySelectorAll('.profile-picker .settings-select-option')].find(button => button.textContent.includes('自定义端点')).click()");
  assert.ok(await evaluate("document.querySelector('.settings-dialog').open"));
  assert.ok(await evaluate("!!document.querySelector('.settings-dialog .advanced-options')"));
  for (let i = 0; i < 100; i++) {
    if (await evaluate("!!document.querySelector('.settings-dialog [aria-label=\"请求地址\"]')")) break;
    await delay(100);
  }
  assert.ok(await evaluate("!!document.querySelector('.settings-dialog [aria-label=\"请求地址\"]')"));
  assert.equal(await evaluate("document.querySelector('[aria-label=\"鉴权Header\"] [aria-pressed=true]').textContent.trim()"), 'Authorization');
  assert.equal(await evaluate("document.querySelectorAll('[aria-label=\"鉴权值格式\"]').length"), 0, 'no separate authentication format selector');
  await evaluate("[...document.querySelectorAll('[aria-label=\"鉴权Header\"] button')].find(button => button.textContent === 'x-api-key').click()");
  await settle();
  assert.equal(await evaluate("document.querySelector('[aria-label=\"鉴权Header\"] [aria-pressed=true]').textContent.trim()"), 'x-api-key');
  await evaluate("[...document.querySelectorAll('[aria-label=\"鉴权Header\"] button')].find(button => button.textContent === 'Authorization').click()");
  await settle();
  assert.equal(await evaluate("document.querySelector('[aria-label=\"鉴权Header\"] [aria-pressed=true]').textContent.trim()"), 'Authorization');
  assert.equal(await evaluate("document.querySelectorAll('.settings-dialog .model-picker-groups').length"), 0, 'model suggestions start collapsed');
  await evaluate("document.querySelector('.protocol-picker .settings-select-trigger').click()");
  await settle();
  assert.equal(await evaluate("document.querySelectorAll('.protocol-picker .settings-select-option').length"), 3);
  assert.equal(await evaluate("document.querySelector('.protocol-picker .settings-select-trigger').getAttribute('aria-expanded')"), 'true');
  assert.equal(await evaluate("getComputedStyle(document.querySelector('.protocol-picker .settings-select-options')).backgroundColor"), 'rgb(43, 43, 43)');
  await evaluate("[...document.querySelectorAll('.protocol-picker .settings-select-option')].find(button => button.textContent.includes('anthropic_messages')).click()");
  await settle();
  assert.equal(await evaluate("document.querySelector('.protocol-picker .settings-select-trigger').textContent.trim()"), 'anthropic_messages');
  assert.equal(await evaluate("document.querySelector('.protocol-picker .settings-select-options')"), null);
  await evaluate("document.querySelector('.protocol-picker .settings-select-trigger').click()");
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await settle();
  assert.equal(await evaluate("document.querySelector('.settings-dialog').open"), true, 'Escape closes only the protocol menu');
  assert.equal(await evaluate("document.querySelector('.protocol-picker .settings-select-options')"), null);
  await evaluate("document.querySelector('.profile-picker .settings-select-trigger').click()");
  await settle();
  await evaluate("[...document.querySelectorAll('.profile-picker .settings-select-option')].find(button => button.textContent.includes('test-profile')).click()");
  for (let i = 0; i < 100; i++) {
    if (await evaluate("!!document.querySelector('#advanced-main-model') && document.querySelector('.profile-picker .settings-select-trigger')?.textContent.includes('test-profile')")) break;
    await delay(50);
  }
  await evaluate("document.querySelector('#advanced-main-model').focus(); document.querySelector('#advanced-main-model').click()");
  await settle();
  assert.equal(await evaluate("document.querySelectorAll('.settings-dialog .model-picker-groups').length"), 1, 'only the selected model suggestions expand');
  assert.equal(await evaluate("document.querySelector('#advanced-main-model').getAttribute('aria-expanded')"), 'true');
  await evaluate("document.querySelector('#advanced-auxiliary-model').scrollIntoView({ block: 'center' })");
  await settle();
  const auxiliaryPoint = await evaluate("(() => { const r = document.querySelector('#advanced-auxiliary-model').getBoundingClientRect(); return { x: r.x + 30, y: r.y + r.height / 2 }; })()");
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', ...auxiliaryPoint, button: 'left', clickCount: 1 });
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', ...auxiliaryPoint, button: 'left', clickCount: 1 });
  await settle();
  if (await evaluate("document.querySelector('#advanced-auxiliary-model').getAttribute('aria-expanded')") === 'false') {
    await evaluate("document.querySelector('#advanced-auxiliary-model').click()");
    await settle();
  }
  assert.equal(await evaluate("document.querySelector('#advanced-main-model').getAttribute('aria-expanded')"), 'false', 'switching fields collapses previous suggestions');
  assert.equal(await evaluate("document.querySelector('#advanced-auxiliary-model').getAttribute('aria-expanded')"), 'true', JSON.stringify(await evaluate("(() => { const el = document.querySelector('#advanced-auxiliary-model'); const r = el.getBoundingClientRect(); return { r: {x:r.x,y:r.y,width:r.width,height:r.height}, active:document.activeElement?.id, hit:document.elementFromPoint(r.x+30,r.y+r.height/2)?.outerHTML.slice(0,160), open:document.querySelectorAll('.model-picker-groups').length }; })()")));
  await evaluate("document.querySelector('#advanced-auxiliary-model').click()");
  await settle();
  assert.equal(await evaluate("document.querySelectorAll('.settings-dialog .model-picker-groups').length"), 0, 'clicking again collapses suggestions');
  await evaluate("document.querySelector('#advanced-main-model').click()");
  await settle();
  await evaluate("document.querySelector('#advanced-main-model-suggestions .model-picker-item').click()");
  await settle();
  assert.equal(await evaluate("document.querySelectorAll('.settings-dialog .model-picker-groups').length"), 0, 'selecting a model collapses suggestions');
  assert.ok(await evaluate("document.querySelector('#advanced-main-model').value.length > 0"));
  assert.equal(await evaluate("document.querySelector('.composer').getBoundingClientRect().top"), composerBeforeSettings);
  const settingsView = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(join(screenshots, 'settings.png'), Buffer.from(settingsView.data, 'base64'));
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await settle();
  assert.equal(await evaluate("document.querySelector('.settings-dialog').open"), false);
  assert.equal(await evaluate("document.activeElement.getAttribute('aria-label')"), '打开设置');
  assert.ok(await evaluate("document.querySelector('.composer').getBoundingClientRect().bottom <= innerHeight"));
  await send("Page.navigate", { url: url.replace('test-session', 'empty-session') });
  for (let i = 0; i < 100; i++) {
    if (await evaluate("!!document.querySelector('.empty-conversation')")) break;
    await delay(100);
  }
  assert.ok(await evaluate("!!document.querySelector('.empty-conversation')"));
  assert.ok(await evaluate("document.querySelector('.composer').getBoundingClientRect().bottom <= innerHeight"));
  console.log("PASS: fixed composer, independent scroll, empty/history states, advanced options, pointer/keyboard resize, persistence, icons, responsive widths, blocked storage");
  console.log(`Screenshots: ${screenshots}`);
} finally {
  const exited = child.exitCode !== null ? Promise.resolve() : once(child, "exit").catch(() => {});
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ id: 999999, method: "Browser.close" }));
  } else {
    child.kill();
  }
  await Promise.race([exited, delay(5000)]);
  if (child.exitCode === null) { child.kill(); await exited; }
  socket?.close();
  server.closeAllConnections();
  await new Promise((resolve) => server.close(resolve));
  rmSync(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
}
