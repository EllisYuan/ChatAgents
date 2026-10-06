/* global WebSocket, process, URL, fetch, console */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { dirname, extname, join, resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const browser = process.env.BROWSER_PATH ?? [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/chromium", "/usr/bin/google-chrome",
].find(existsSync);
assert.ok(browser, "Set BROWSER_PATH to an installed Chromium browser");
const profile = mkdtempSync(join(tmpdir(), "chatagents-message-scroll-"));
let runResponse;
const server = createServer((request, response) => {
  const path = new URL(request.url, "http://localhost").pathname;
  if (path === "/api/runs" && request.method === "POST") {
    request.resume();
    response.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
    response.write('data: {"type":"RUN_STARTED","runId":"test-run"}\n\n');
    runResponse = response;
    return;
  }
  if (path.startsWith("/api/")) {
    response.setHeader("Content-Type", "application/json");
    if (path === "/api/sessions/test-session") {
      response.end(JSON.stringify({
        id: "test-session", title: "滚动回归", created_at: "2026-10-03T10:00:00Z", updated_at: "2026-10-03T10:00:00Z",
        messages: Array.from({ length: 20 }, (_, i) => ({
          id: `message-${i}`, seq: i, role: i % 2 ? "assistant" : "user",
          content: [{ type: "text", text: `历史消息 ${i}。这里有足够长的内容，让聊天内容区需要滚动。`.repeat(3) }],
        })),
      }));
    } else if (path === "/api/sessions") response.end("[]");
    else if (path === "/api/models/profiles") response.end(JSON.stringify({ profiles: [{ name: "test-profile", status: "available", main_model: "default-model", auxiliary_model: null }], default_profile: "test-profile" }));
    else if (path === "/api/models") response.end(JSON.stringify({ models: [{ id: "default-model", owned_by: "test" }] }));
    else if (path.endsWith("/runs")) response.end("[]");
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
  socket.addEventListener("message", ({ data }) => {
    const message = JSON.parse(data);
    const entry = pending.get(message.id);
    if (!entry) return;
    pending.delete(message.id);
    if (message.error) entry.reject(message.error);
    else entry.resolve(message.result);
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const key = ++id;
    pending.set(key, { resolve, reject });
    socket.send(JSON.stringify({ id: key, method, params }));
  });
  await send("Runtime.enable");
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 800, deviceScaleFactor: 1, mobile: false });
  const evaluate = async (expression) => {
    const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    assert.equal(result.exceptionDetails, undefined, JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  const settle = () => evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))");
  const waitFor = async (expression) => {
    for (let i = 0; i < 100; i++) {
      if (await evaluate(expression)) return;
      await delay(50);
    }
    assert.fail(`Timed out waiting for ${expression}`);
  };
  const bottomGap = () => evaluate("(() => { const el = document.querySelector('.message-scroll'); return Math.round(el.scrollHeight - el.clientHeight - el.scrollTop); })()");
  const assertBottom = async (stage) => assert.ok(await bottomGap() <= 2, `${stage}: message scroll bottom gap ${await bottomGap()}px`);
  await send("Page.navigate", { url: `http://127.0.0.1:${server.address().port}/s/test-session` });
  await waitFor("document.querySelectorAll('.chat-turn').length === 20");
  await evaluate("document.querySelector('.message-scroll').scrollTop = 100000");
  await settle();
  await assertBottom("before send");
  await evaluate(`(() => { const input = document.querySelector('.composer-input'); const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set; setter.call(input, '新的提问'); input.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await settle();
  await evaluate("document.querySelector('.composer button[type=submit]').click()");
  await waitFor("!!document.querySelector('.config-confirmation')");
  await evaluate("document.querySelector('.config-confirmation .settings-done').click()");
  await waitFor("document.querySelectorAll('.chat-turn').length === 22 && !!document.querySelector('.composer-submit--stop')");
  await settle();
  await assertBottom("after send");
  for (const [index, delta] of ["第一段回答。".repeat(40), "第二段回答。".repeat(40)].entries()) {
    runResponse.write(`data: ${JSON.stringify({ type: "TEXT_MESSAGE_CONTENT", messageId: "assistant", delta })}\n\n`);
    await waitFor(`document.querySelectorAll('.chat-turn')[21]?.textContent.includes('${index ? "第二段" : "第一段"}')`);
    await settle();
    await assertBottom(`after delta ${index + 1}`);
  }
  await evaluate("document.querySelector('.message-scroll').scrollTop -= 250");
  await settle();
  const gapWhileReading = await bottomGap();
  assert.ok(gapWhileReading > 100, "manual scroll should leave the bottom");
  runResponse.write(`data: ${JSON.stringify({ type: "TEXT_MESSAGE_CONTENT", messageId: "assistant", delta: "继续输出。".repeat(40) })}\n\n`);
  await waitFor("document.querySelectorAll('.chat-turn')[21]?.textContent.includes('继续输出')");
  await settle();
  assert.ok(await bottomGap() >= gapWhileReading - 2, "new content must not pull a reader away from history");
  await evaluate("document.querySelector('.message-scroll').scrollTop = 100000");
  await settle();
  runResponse.write(`data: ${JSON.stringify({ type: "TEXT_MESSAGE_CONTENT", messageId: "assistant", delta: "末段回答。".repeat(40) })}\n\n`);
  await waitFor("document.querySelectorAll('.chat-turn')[21]?.textContent.includes('末段回答')");
  await settle();
  await assertBottom("after returning to bottom");
  runResponse.end('data: {"type":"RUN_FINISHED"}\n\n');
  await waitFor("!document.querySelector('.composer-submit--stop') && document.querySelectorAll('.chat-turn').length === 22");
  await settle();
  await assertBottom("after run finished");
  await evaluate("document.querySelector('.message-scroll').scrollTop = 0");
  await settle();
  assert.ok(await bottomGap() > 100, "history must be scrollable before the next send");
  await evaluate(`(() => { const input = document.querySelector('.composer-input'); const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set; setter.call(input, '再问一次'); input.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await settle();
  await evaluate("document.querySelector('.composer button[type=submit]').click()");
  await waitFor("document.querySelectorAll('.chat-turn').length === 24 && !!document.querySelector('.composer-submit--stop')");
  await settle();
  await assertBottom("new send from history");
  runResponse.end('data: {"type":"RUN_FINISHED"}\n\n');
  console.log("PASS: messages and streamed text follow the bottom; manual reading position is preserved");
} finally {
  runResponse?.end();
  const exited = child.exitCode !== null ? Promise.resolve() : once(child, "exit").catch(() => {});
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ id: 999999, method: "Browser.close" }));
  else child.kill();
  await Promise.race([exited, delay(5000)]);
  if (child.exitCode === null) { child.kill(); await exited; }
  socket?.close();
  server.closeAllConnections();
  await new Promise((resolve) => server.close(resolve));
  rmSync(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
}
