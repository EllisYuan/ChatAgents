/* global AbortController, URL, fetch, process, setTimeout */

import assert from "node:assert/strict";
import { once } from "node:events";
import { createServer as createHttpServer } from "node:http";
import { afterEach, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer as createViteServer } from "vite";

let backend;
let vite;

afterEach(async () => {
  await vite?.close();
  await new Promise((resolve, reject) => {
    if (!backend) return resolve();
    backend.close((error) => error ? reject(error) : resolve());
    backend.closeAllConnections();
  });
  vite = null;
  backend = null;
});

test("浏览器中止标题 fetch 时 Vite proxy 关闭后端连接", async () => {
  let markStarted;
  let markDisconnected;
  const started = new Promise((resolve) => { markStarted = resolve; });
  const disconnected = new Promise((resolve) => { markDisconnected = resolve; });
  backend = createHttpServer((request, response) => {
    assert.equal(request.url, "/api/sessions/test/title");
    assert.equal(request.method, "POST");
    request.resume();
    request.on("end", markStarted);
    response.on("close", markDisconnected);
  });
  backend.listen(0, "127.0.0.1");
  await once(backend, "listening");
  const backendPort = backend.address().port;
  const previousOrigin = process.env.VITE_BACKEND_ORIGIN;
  process.env.VITE_BACKEND_ORIGIN = `http://127.0.0.1:${backendPort}`;
  try {
    vite = await createViteServer({
      configFile: fileURLToPath(new URL("../vite.config.ts", import.meta.url)),
      server: { host: "127.0.0.1", port: 0 },
      logLevel: "silent",
    });
    await vite.listen();
    const proxyPort = vite.httpServer.address().port;
    const controller = new AbortController();
    const fetchTask = fetch(`http://127.0.0.1:${proxyPort}/api/sessions/test/title`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}",
      signal: controller.signal,
    });
    await Promise.race([started, timeout("后端未收到标题请求")]);
    controller.abort();
    await assert.rejects(fetchTask, { name: "AbortError" });
    await Promise.race([disconnected, timeout("Vite proxy 未关闭后端连接")]);
  } finally {
    if (previousOrigin === undefined) delete process.env.VITE_BACKEND_ORIGIN;
    else process.env.VITE_BACKEND_ORIGIN = previousOrigin;
  }
});

function timeout(message) {
  return new Promise((_, reject) => {
    const timer = setTimeout(() => reject(new Error(message)), 3000);
    timer.unref();
  });
}
