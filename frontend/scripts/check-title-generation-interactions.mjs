/* global TextEncoder, ReadableStream, setTimeout */

import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { JSDOM } from "jsdom";

/*
 * issue #93 的页面级可见行为测试——控制 HTTP/SSE 输入，断言用户能观察到的结果：
 * 首次 RUN_STARTED 用发送时的配置快照发起独立标题调用、
 * 导航/卸载取消标题且迟到结果不污染状态、人工改名与删除优先于迟到模型标题。
 *
 * 不依赖内部 hook 状态或组件私有实现：只经由 SessionPage 的 DOM 与 fetch 请求
 * 观察行为。项目无 Vitest/RTL（issue #17），使用 node:test + jsdom + react-dom/client。
 *
 * react-dom 必须在 DOM 全局装配**之后**动态 import：它在模块求值时就检测
 * `canUseDOM`，静态 import 会让输入事件的全套 change-event 支持停用（受控
 * textarea 的 onChange 永不触发）。
 */
const dom = new JSDOM("<!doctype html><html><body><main id='root'></main></body></html>", {
  url: "http://localhost",
});
Object.assign(globalThis, { window: dom.window, document: dom.window.document });

const React = await import("react");
const { createElement, act } = React;
const { createRoot } = await import("react-dom/client");
const { QueryClient, QueryClientProvider } = await import("@tanstack/react-query");
const { Link, MemoryRouter, Route, Routes } = await import("react-router-dom");
Object.assign(globalThis, { React, IS_REACT_ACT_ENVIRONMENT: true });

const { SessionPage } = await import("../src/features/session/SessionPage.tsx");
const { SessionListItem } = await import("../src/features/sessions/SessionListItem.tsx");
const { useSessionListStore } = await import("../src/stores/session-list-store.ts");
const { useModelOptionsStore, CUSTOM_PROFILE } = await import("../src/stores/model-options-store.ts");

const encoder = new TextEncoder();
const ENVELOPE_STARTED = { type: "RUN_STARTED", runId: "run-1" };
const ENVELOPE_FINISHED = { type: "RUN_FINISHED" };

let root = null;
let queryClient = null;
let sessionCounter = 0;
let titleRequests = [];
let titleResolvers = [];
let runStreams = [];
let renamedPayload = null;
let existingSessionIds = new Set();

function freshSessionId() {
  sessionCounter += 1;
  return `0b7c9f2a-0000-7000-8000-0000000000${String(sessionCounter).padStart(2, "0")}`;
}

function installFetch() {
  titleRequests = [];
  titleResolvers = [];
  runStreams = [];
  globalThis.fetch = (url, options = {}) => {
    const method = options.method ?? "GET";
    // 标题生成：可手动 resolve 的悬挂请求，signal 由调用方传入。
    if (typeof url === "string" && url.endsWith("/title") && method === "POST") {
      titleRequests.push({ url, options, body: JSON.parse(options.body) });
      return new Promise((resolve) => titleResolvers.push(resolve));
    }
    // 主运行：每次 POST 一条可控 SSE 流，测试决定何时推帧、何时收尾。
    if (url === "/api/runs" && method === "POST") {
      let controller;
      const body = new ReadableStream({ start(c) { controller = c; } });
      const entry = { controller, signal: options.signal, request: JSON.parse(options.body) };
      runStreams.push(entry);
      return Promise.resolve({ ok: true, body });
    }
    if (method === "GET" && /^\/api\/sessions\/[^/]+$/.test(url)) {
      const id = url.split("/").at(-1);
      if (existingSessionIds.has(id)) {
        return Promise.resolve({ ok: true, json: async () => ({ id, title: "已有标题", messages: [] }) });
      }
      return Promise.resolve({ status: 404, ok: false, json: async () => ({}) });
    }
    if (method === "GET" && url.endsWith("/runs")) {
      return Promise.resolve({ ok: true, json: async () => [] });
    }
    if (method === "GET" && url === "/api/models/profiles") {
      return Promise.resolve({ ok: true, json: async () => ({ profiles: [], default_profile: null }) });
    }
    if (method === "PATCH") {
      return Promise.resolve({ ok: true, json: async () => renamedPayload });
    }
    if (method === "DELETE") {
      return Promise.resolve({ ok: true, status: 204 });
    }
    throw new Error(`unexpected fetch: ${method} ${url}`);
  };
}

async function tick() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function pushFrame(entry, envelope) {
  await act(async () => {
    entry.controller.enqueue(encoder.encode(`data: ${JSON.stringify(envelope)}\n\n`));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function closeStream(entry) {
  await act(async () => {
    entry.controller.close();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function mount(sessionId, nextSessionId = null) {
  root = createRoot(dom.window.document.getElementById("root"));
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      createElement(
        QueryClientProvider,
        { client: queryClient },
        createElement(
          MemoryRouter,
          { initialEntries: [`/s/${sessionId}`] },
          createElement(
            Routes,
            {},
            createElement(Route, {
              path: "/s/:sessionId",
              element: createElement(
                React.Fragment,
                {},
                nextSessionId && createElement(Link, { to: `/s/${nextSessionId}` }, "切换会话"),
                createElement(SessionPage),
              ),
            }),
          ),
        ),
      ),
    );
  });
  await tick();
  return dom.window.document.getElementById("root");
}

async function send(container, text) {
  const textarea = container.querySelector(".composer-input");
  const valueSetter = Object.getOwnPropertyDescriptor(
    dom.window.HTMLTextAreaElement.prototype,
    "value",
  ).set;
  await act(async () => {
    valueSetter.call(textarea, text);
    textarea.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
  });
  const form = container.querySelector('form[aria-label="发送消息"]');
  await act(async () => {
    form.dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function sessionById(sessionId) {
  return useSessionListStore.getState().sessions.find((s) => s.id === sessionId) ?? null;
}

afterEach(async () => {
  if (root) {
    await act(async () => root.unmount());
  }
  root = null;
  queryClient?.clear();
  queryClient = null;
  existingSessionIds = new Set();
  dom.window.document.getElementById("root").replaceChildren();
  useSessionListStore.setState({ sessions: [], loaded: false, error: null });
  useModelOptionsStore.getState().setSystemDefault();
  delete globalThis.fetch;
});

test("首次 RUN_STARTED 用发送时的配置快照发起独立标题调用，后续消息不补发", async () => {
  installFetch();
  const sessionId = freshSessionId();
  const container = await mount(sessionId);
  // 装载后把界面配置切成自定义端点 main-A（真实 UI 流程：会话加载后用户填写配置）。
  const store = useModelOptionsStore.getState();
  store.setProfileChoice(CUSTOM_PROFILE);
  store.setCustomField("baseUrl", "https://relay.example/v1");
  store.setCustomField("apiKey", "secret");
  store.setMainModel("main-A");

  await send(container, "第一条消息");
  assert.equal(runStreams.length, 1, "发送应发起一次主运行");
  assert.equal(runStreams[0].request.model_override.auth_field, "Authorization", "主运行使用发送时的鉴权 Header");

  // 主运行尚未 STARTED 时改界面配置——快照必须在发送时固定，不能在这里被读走。
  store.setMainModel("main-B");
  store.setCustomField("apiKey", "changed");
  store.setCustomField("authField", "x-api-key");

  await pushFrame(runStreams[0], ENVELOPE_STARTED);
  assert.equal(titleRequests.length, 1, "RUN_STARTED 后应发起一次标题调用");
  assert.equal(titleRequests[0].url, `/api/sessions/${sessionId}/title`);
  assert.equal(titleRequests[0].body.model_override.main_model, "main-A", "快照固定在发送时");
  assert.equal(titleRequests[0].body.model_override.api_key, "secret", "快照固定在发送时");
  assert.equal(titleRequests[0].body.model_override.auth_field, "Authorization", "鉴权 Header 也固定在发送时");
  assert.equal(titleRequests[0].body.model_override.main_model === "main-B", false);

  // 标题先于主运行完成：独立完成、不等待主回答。
  await act(async () => {
    titleResolvers[0]({ ok: true, json: async () => ({ session_id: sessionId, title: "模型标题", status: "applied" }) });
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  assert.equal(sessionById(sessionId)?.title, "模型标题", "标题响应立即应用到列表");

  await pushFrame(runStreams[0], ENVELOPE_FINISHED);
  await closeStream(runStreams[0]);
  await tick();

  // 主运行结束后的后续消息不得再次自动生成标题（至多一次）。
  await send(container, "第二条消息");
  assert.equal(runStreams.length, 2, "第二条消息发起第二次主运行");
  await pushFrame(runStreams[1], ENVELOPE_STARTED);
  assert.equal(titleRequests.length, 1, "后续消息不补发标题调用");
  await pushFrame(runStreams[1], ENVELOPE_FINISHED);
  await closeStream(runStreams[1]);
  await tick();
});

test("主运行完成不取消尚未完成的标题", async () => {
  installFetch();
  const sessionId = freshSessionId();
  const container = await mount(sessionId);
  await send(container, "第一条消息");
  await pushFrame(runStreams[0], ENVELOPE_STARTED);
  await pushFrame(runStreams[0], ENVELOPE_FINISHED);
  await closeStream(runStreams[0]);
  assert.equal(titleRequests[0].options.signal.aborted, false);

  await act(async () => {
    titleResolvers[0]({ ok: true, json: async () => ({ session_id: sessionId, title: "主运行结束后的标题", status: "applied" }) });
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  assert.equal(sessionById(sessionId)?.title, "主运行结束后的标题");
});

test("主运行失败不取消尚未完成的标题", async () => {
  installFetch();
  const sessionId = freshSessionId();
  const container = await mount(sessionId);
  await send(container, "第一条消息");
  await pushFrame(runStreams[0], ENVELOPE_STARTED);
  await pushFrame(runStreams[0], { type: "RUN_ERROR", message: "模型失败" });
  await closeStream(runStreams[0]);
  assert.equal(titleRequests[0].options.signal.aborted, false);

  await act(async () => {
    titleResolvers[0]({ ok: true, json: async () => ({ session_id: sessionId, title: "失败后完成的标题", status: "applied" }) });
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  assert.equal(sessionById(sessionId)?.title, "失败后完成的标题");
});

test("导航/卸载取消尚未完成的标题调用，迟到响应不污染状态", async () => {
  installFetch();
  const sessionId = freshSessionId();
  const container = await mount(sessionId);
  await send(container, "第一条消息");
  await pushFrame(runStreams[0], ENVELOPE_STARTED);
  assert.equal(titleRequests.length, 1);
  assert.equal(titleRequests[0].options.signal.aborted, false);

  await act(async () => root.unmount());
  root = null;

  assert.equal(titleRequests[0].options.signal.aborted, true, "离开页面应取消标题调用");

  // 取消后到达的响应不得写回列表。
  await act(async () => {
    titleResolvers[0]({ ok: true, json: async () => ({ session_id: sessionId, title: "迟到标题", status: "applied" }) });
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  assert.equal(sessionById(sessionId)?.title ?? null, null, "迟到结果不覆盖本地状态");
  void container;
});

test("切换会话取消旧标题请求，迟到响应不写回另一会话", async () => {
  installFetch();
  const firstId = freshSessionId();
  const secondId = freshSessionId();
  const container = await mount(firstId, secondId);
  await send(container, "第一条消息");
  await pushFrame(runStreams[0], ENVELOPE_STARTED);
  assert.equal(titleRequests.length, 1);

  await act(async () => {
    container.querySelector("a").click();
  });
  await tick();
  assert.equal(titleRequests[0].options.signal.aborted, true, "切换会话应取消旧标题请求");
  assert.equal(container.querySelector(".composer-input") !== null, true, "页面应显示新会话输入区");

  await act(async () => {
    titleResolvers[0]({ ok: true, json: async () => ({ session_id: firstId, title: "迟到标题", status: "applied" }) });
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  assert.equal(sessionById(firstId)?.title ?? null, null, "旧会话的迟到响应不得应用");
  assert.equal(sessionById(secondId)?.title ?? null, null, "新会话不受旧响应影响");
  assert.equal(titleRequests.length, 1, "导航本身不应补发标题请求");
});

test("已有会话重新进入后不补发标题调用", async () => {
  installFetch();
  const sessionId = freshSessionId();
  existingSessionIds.add(sessionId);
  const container = await mount(sessionId);
  assert.equal(container.querySelector(".composer-input") !== null, true);
  assert.equal(titleRequests.length, 0);
});

test("会话改名后迟到的模型响应不能覆盖人工标题", async () => {
  installFetch();
  const sessionId = freshSessionId();
  const container = await mount(sessionId);
  await send(container, "第一条消息");
  await pushFrame(runStreams[0], ENVELOPE_STARTED);
  assert.equal(titleRequests.length, 1);

  const listRoot = dom.window.document.createElement("div");
  dom.window.document.body.append(listRoot);
  const list = createRoot(listRoot);
  const now = new Date().toISOString();
  renamedPayload = { id: sessionId, title: "人工标题", created_at: now, updated_at: now, pruned_run_count: 0 };
  try {
    await act(async () => list.render(createElement(
      MemoryRouter, {}, createElement(SessionListItem, {
        session: { id: sessionId, title: null, created_at: now, updated_at: now, message_count: 1 },
        active: true,
      }),
    )));
    assert.equal(listRoot.querySelector('[aria-label="标题生成详情"]'), null);
    assert.deepEqual(
      [...listRoot.querySelectorAll(".session-item-action")].map((button) => button.getAttribute("aria-label")),
      ["重命名会话", "删除会话"],
    );
    await act(async () => listRoot.querySelector('[aria-label="重命名会话"]').click());
    const input = listRoot.querySelector("input");
    const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value").set;
    await act(async () => {
      setter.call(input, "人工标题");
      input.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });
    await act(async () => {
      input.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    assert.equal(sessionById(sessionId)?.title, "人工标题");
    await act(async () => {
      titleResolvers[0]({ ok: true, json: async () => ({ session_id: sessionId, title: "迟到模型标题", status: "applied" }) });
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    assert.equal(sessionById(sessionId)?.title, "人工标题");
  } finally {
    await act(async () => list.unmount());
    listRoot.remove();
  }
});

test("人工改名后的刷新仍采用服务端更新的活动时间", async () => {
  installFetch();
  const sessionId = freshSessionId();
  const before = "2026-10-03T10:00:00.000Z";
  const after = "2026-10-03T11:00:00.000Z";
  renamedPayload = { id: sessionId, title: "人工标题", created_at: before, updated_at: before, pruned_run_count: 0 };
  await useSessionListStore.getState().rename(sessionId, "人工标题");
  const previousFetch = globalThis.fetch;
  globalThis.fetch = (url, options) => {
    if (url === `/api/sessions/${sessionId}`) {
      return Promise.resolve({ ok: true, json: async () => ({ id: sessionId, title: "人工标题", created_at: before, updated_at: after, messages: [{}, {}] }) });
    }
    return previousFetch(url, options);
  };
  await useSessionListStore.getState().refreshSession(sessionId);
  assert.equal(sessionById(sessionId)?.title, "人工标题");
  assert.equal(sessionById(sessionId)?.updated_at, after);
  assert.equal(sessionById(sessionId)?.message_count, 2);
});

test("人工改名与删除优先于迟到的模型标题（store 保护）", async () => {
  installFetch();
  const sessionId = freshSessionId();
  const now = new Date().toISOString();
  renamedPayload = { id: sessionId, title: "人工标题", created_at: now, updated_at: now, pruned_run_count: 0 };

  await useSessionListStore.getState().rename(sessionId, "人工标题");
  assert.equal(sessionById(sessionId)?.title, "人工标题");

  // 模型结果在其后到达——必须被人工改名保护挡住。
  useSessionListStore.getState().applyTitle(sessionId, "模型标题");
  assert.equal(sessionById(sessionId)?.title, "人工标题", "人工改名优先于迟到的模型标题");

  // 删除后迟到的结果不得复活该行。
  await useSessionListStore.getState().remove(sessionId);
  assert.equal(sessionById(sessionId), null, "删除生效");
  useSessionListStore.getState().applyTitle(sessionId, "复活标题");
  assert.equal(sessionById(sessionId), null, "迟到结果不复活已删除会话");
});
