/* global console, process, URL */

import assert from "node:assert/strict";
import { readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const STORAGE_KEY = "chatagents:model-options:v1";
const outfile = join(tmpdir(), `chatagents-model-options-${process.pid}.mjs`);
const helperOutfile = join(tmpdir(), `chatagents-model-endpoint-${process.pid}.mjs`);
const values = new Map();
globalThis.window = {
  localStorage: {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  },
};

try {
  await esbuild.build({
    entryPoints: ["src/stores/model-options-store.ts"],
    bundle: true,
    format: "esm",
    platform: "node",
    outfile,
  });
  const store = await import(`${pathToFileURL(outfile).href}?check=${Date.now()}`);
  await esbuild.build({
    entryPoints: ["src/features/session/model-endpoint.ts"],
    bundle: true,
    format: "esm",
    platform: "node",
    outfile: helperOutfile,
  });
  const endpoint = await import(`${pathToFileURL(helperOutfile).href}?check=${Date.now()}`);
  const options = store.useModelOptionsStore;

  let defaultUpdates = 0;
  const unsubscribe = options.subscribe(() => {
    defaultUpdates += 1;
  });
  options.getState().setDefaultProfile("server-default");
  defaultUpdates = 0;
  options.getState().setDefaultProfile("server-default");
  assert.equal(defaultUpdates, 0, "same default profile must be a no-op");
  unsubscribe();

  options.getState().setProfileChoice(store.CUSTOM_PROFILE);
  options.getState().setCustomField("baseUrl", "https://example.test/v1");
  options.getState().setCustomField("apiKey", "secret");
  options.getState().setCustomCatalog({ models: [], source: "discovered", error: null });
  options.getState().setCustomStatus("error", "transient");
  options.getState().setCustomField("baseUrl", "https://example.test/v1");
  assert.notEqual(options.getState().customCatalog, null, "unchanged connection input must preserve the catalog");
  assert.equal(options.getState().customStatus, "error", "unchanged connection input must preserve transient status");
  options.getState().setCustomField("baseUrl", "https://example.test/v2");
  assert.equal(options.getState().customCatalog, null, "changed connection input must clear the catalog");
  assert.equal(options.getState().customStatus, "idle", "changed connection input must clear transient status");
  assert.equal(options.getState().customErrorMessage, null, "changed connection input must clear transient errors");
  options.getState().setCustomField("baseUrl", "https://example.test/v1");
  options.getState().setMainModel("custom-main");
  options.getState().setAuxiliaryModel("custom-aux");
  options.getState().setProfileChoice("server-default");
  assert.equal(options.getState().mainModel, "", "leaving custom resets active preset model");
  options.getState().setProfileChoice(store.CUSTOM_PROFILE);
  assert.equal(options.getState().mainModel, "custom-main", "custom main draft survives profile switch");
  assert.equal(options.getState().auxiliaryModel, "custom-aux", "custom auxiliary draft survives profile switch");

  const config = store.buildSessionModelConfig(options.getState(), "high");
  assert.equal(store.persistSessionModelConfig("session-1", config), true);
  options.getState().setSystemDefault();
  store.restoreSessionModelConfig("session-1", true);
  options.getState().setProfileChoice(store.CUSTOM_PROFILE);
  assert.equal(options.getState().mainModel, "custom-main", "custom draft survives Session restore");
  assert.equal(options.getState().auxiliaryModel, "custom-aux", "custom auxiliary survives Session restore");

  options.getState().setSystemDefault();
  options.getState().setMainModel("explicit-system-model");
  const override = store.buildModelOverride(options.getState());
  assert.deepEqual(override, { kind: "override", override: { main_model: "explicit-system-model" } });

  const inherited = store.restoreSessionModelConfig("new-session", false);
  assert.deepEqual(inherited, config, "new Session inherits the last saved configuration");
  assert.equal(options.getState().custom.apiKey, "secret", "API key survives restore");
  options.getState().setMainModel("second-main");
  const secondConfig = store.buildSessionModelConfig(options.getState(), "low");
  store.persistSessionModelConfig("session-2", secondConfig);
  assert.deepEqual(store.restoreSessionModelConfig("session-1", true), config, "existing Session retains its own configuration");
  assert.deepEqual(store.restoreSessionModelConfig("another-new-session", false), secondConfig, "new Session uses the latest saved configuration");
  assert.equal(store.restoreSessionModelConfig("unknown-existing-session", true), null, "existing Session must not inherit latest implicitly");
  assert.equal(options.getState().custom.apiKey, "", "missing Session configuration clears previous credentials");

  // 预览必须与后端解析器逐条一致，否则界面又会告诉用户一个假地址（issue #83）。
  const sharedCases = JSON.parse(
    await readFile(new URL("../../backend/tests/fixtures/endpoint_address_cases.json", import.meta.url), "utf8"),
  );
  for (const shared of sharedCases.filter((item) => item.mode !== "sdk_native")) {
    const description = endpoint.describeEndpoint(shared.protocol, `https://relay.example${shared.path}`, shared.mode);
    assert.equal(description.generationPath, shared.generation, `generation ${shared.mode} ${shared.protocol} ${shared.path}`);
    assert.equal(description.discoveryPath, shared.discovery, `discovery ${shared.mode} ${shared.protocol} ${shared.path}`);
  }
  assert.equal(endpoint.describeEndpoint("openai_responses", "https://relay.example?"), null, "empty query delimiter is invalid");
  assert.equal(endpoint.describeEndpoint("openai_responses", "https://user:secret@relay.example/v1"), null, "credentials are invalid");
  assert.equal(endpoint.describeEndpoint("openai_responses", "ftp://relay.example/v1"), null, "non-http URL is invalid");
  assert.equal(endpoint.describeEndpoint("openai_responses", "https://relay.example/v1?api_key=secret"), null, "query-bearing URL is invalid");
  const invalidMessage = endpoint.validateEndpointUrl("https://user:secret@relay.example/v1");
  assert.equal(invalidMessage, "请求地址不是可接受的 HTTP(S) URL", "invalid URL errors stay generic");
  const safeDescription = endpoint.describeEndpoint("openai_responses", "https://relay.example/private");
  assert.equal(JSON.stringify(safeDescription).includes("relay.example"), false, "endpoint previews must not expose the host");
  assert.equal(JSON.stringify(safeDescription).includes("secret"), false, "endpoint previews must not expose credentials or keys");
  assert.equal(JSON.stringify(safeDescription).includes("?"), false, "endpoint previews must not expose queries");
  for (const invalid of ["https://relay.example#", "https://relay.example#secret", "https:relay.example", "https://relay.example/" + String.fromCharCode(1)]) {
    assert.equal(endpoint.describeEndpoint("openai_responses", invalid), null);
  }

  // 旧 Session 配置（没有 fullUrl 这个字段）必须原样还能用，且保留原来的目标地址。
  const legacyBase = {
    profileChoice: store.CUSTOM_PROFILE,
    mainModel: "legacy-main",
    auxiliaryModel: "legacy-main",
    auxiliaryFollowsMain: true,
    mainModelTouched: true,
    customMainModel: "legacy-main",
    customAuxiliaryModel: "legacy-main",
    customAuxiliaryFollowsMain: true,
    customMainModelTouched: true,
    effort: "medium",
  };
  const legacyCases = [
    ["openai_responses", "https://legacy.example", "https://legacy.example", false],
    ["openai_responses", "https://legacy.example/v1", "https://legacy.example/v1", false],
    ["openai_chat_completions", "https://legacy.example/compatible", "https://legacy.example/compatible", false],
    ["anthropic_messages", "https://legacy.example", "https://legacy.example", false],
    // 旧 Anthropic 非根地址：SDK 当时真正打的是 <前缀>/v1/messages，转成完整 URL 才等价。
    ["anthropic_messages", "https://legacy.example/compatible", "https://legacy.example/compatible/v1/messages", true],
    ["anthropic_messages", "https://legacy.example/v1", "https://legacy.example/v1/v1/messages", true],
  ];
  for (const [protocol, storedUrl, expectedUrl, expectedFullUrl] of legacyCases) {
    const legacy = { latest: null, sessions: { legacy: { ...legacyBase, custom: { protocol, baseUrl: storedUrl, authField: "x-api-key", apiKey: "legacy-secret" } } } };
    values.set(STORAGE_KEY, JSON.stringify(legacy));
    const restored = store.restoreSessionModelConfig("legacy", true);
    assert.notEqual(restored, null, "legacy configuration must survive the new field");
    assert.equal(restored.custom.fullUrl, expectedFullUrl, `legacy ${protocol} ${storedUrl} mode`);
    assert.equal(restored.custom.baseUrl, expectedUrl, `legacy ${protocol} ${storedUrl} address`);
    assert.equal(restored.custom.apiKey, "legacy-secret", "migration preserves the key");
    assert.equal(restored.mainModel, "legacy-main", "migration preserves model choices");
    assert.equal(restored.effort, "medium", "migration preserves effort");
    // 幂等：把迁移结果再存一次、再读一次，不能继续追加路径。
    values.set(STORAGE_KEY, JSON.stringify({ latest: null, sessions: { legacy: restored } }));
    const again = store.restoreSessionModelConfig("legacy", true);
    assert.deepEqual(again, restored, "migration must be idempotent");
  }
  values.clear();

  const catalog = { models: [{ id: "fixture", owned_by: "fixture", endpoint_profile: "custom" }], source: "discovered", error: null };
  options.getState().setProfileChoice(store.CUSTOM_PROFILE);
  // 迁移用例留下的是 anthropic + 完整 URL；先回到已知基线，下面每次改动才真的是改动。
  options.getState().setCustomField("protocol", "openai_responses");
  options.getState().setCustomField("fullUrl", false);
  options.getState().setCustomField("authField", "Authorization");
  options.getState().setCustomField("baseUrl", "https://example.test/v1");
  options.getState().setCustomField("apiKey", "secret");
  options.getState().setMainModel("keep-main");
  options.getState().setAuxiliaryModel("keep-auxiliary");
  for (const [field, value] of [["baseUrl", "https://other.example/v1"], ["protocol", "anthropic_messages"], ["authField", "x-api-key"], ["apiKey", "new-secret"], ["fullUrl", true]]) {
    options.getState().setCustomCatalog(catalog);
    const token = options.getState().startCustomRefresh();
    const previous = options.getState().custom[field];
    assert.notEqual(previous, value, `${field} baseline must differ so the edit is a real change`);
    options.getState().setCustomField(field, value);
    options.getState().setCustomField(field, previous);
    options.getState().finishCustomRefresh(token, catalog);
    assert.equal(options.getState().customCatalog, null, "A → B → A must invalidate the old response");
    assert.equal(options.getState().mainModel, "keep-main", "connection edits preserve model choices");
    assert.equal(options.getState().auxiliaryModel, "keep-auxiliary");
  }
  const older = options.getState().startCustomRefresh();
  const newer = options.getState().startCustomRefresh();
  options.getState().finishCustomRefresh(older, "stale error");
  assert.equal(options.getState().customStatus, "loading", "older responses cannot finish a newer request");
  options.getState().finishCustomRefresh(newer, catalog);
  options.getState().finishCustomRefresh(older, catalog);
  assert.deepEqual(options.getState().customCatalog, catalog);
  assert.equal(options.getState().customStatus, "idle");
  const beforeSessionChange = options.getState().startCustomRefresh();
  store.restoreSessionModelConfig("session-1", true);
  options.getState().finishCustomRefresh(beforeSessionChange, catalog);
  assert.equal(options.getState().customCatalog, null, "Session restore invalidates outstanding discovery");
  const beforeMissingSession = options.getState().startCustomRefresh();
  store.restoreSessionModelConfig("unknown-existing-session", true);
  options.getState().finishCustomRefresh(beforeMissingSession, "stale failure");
  assert.equal(options.getState().customStatus, "idle");
  assert.equal(options.getState().customErrorMessage, null);
  const failed = options.getState().startCustomRefresh();
  options.getState().finishCustomRefresh(failed, "discovery failed");
  assert.equal(options.getState().customStatus, "error");
  assert.equal(options.getState().customErrorMessage, "discovery failed");

  options.getState().setSystemDefault();
  assert.deepEqual(store.buildModelOverride(options.getState()), { kind: "none" });
  options.getState().setDefaultProfile("new-server-default");
  assert.deepEqual(store.buildModelOverride(options.getState()), { kind: "none" }, "system default follows server changes");

  for (const key of values.keys()) values.set(key, "invalid JSON");
  assert.equal(store.restoreSessionModelConfig("session-1", true), null, "corrupt storage must not crash restore");
  globalThis.window.localStorage.setItem = () => { throw new Error("quota exceeded"); };
  assert.equal(store.persistSessionModelConfig("session-1", config), false, "write failure must be reported");
  globalThis.window.localStorage.getItem = () => { throw new Error("storage blocked"); };
  assert.equal(store.restoreSessionModelConfig("session-1", true), null, "blocked storage must not crash restore");

  console.log("model-options regression checks passed: endpoint paths, URL validation, stale discovery responses, profile switching, Session isolation, default inheritance, API key restore, dynamic defaults, storage failures");
} finally {
  await rm(outfile, { force: true });
  await rm(helperOutfile, { force: true });
}
