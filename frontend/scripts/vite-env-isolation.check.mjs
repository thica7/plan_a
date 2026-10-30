// Evaluate the config with loadEnv intercepted before any env-file read.
import assert from "node:assert/strict";
import fs, { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { devNull, tmpdir } from "node:os";
import { join, basename } from "node:path";
import { test } from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const configUrl = new URL("../vite.config.ts", import.meta.url);
const source = readFileSync(configUrl, "utf8").replaceAll("import.meta.url", JSON.stringify(configUrl.href));
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText;

function evaluate(env) {
  const calls = [];
  const exports = {};
  vm.runInNewContext(compiled, {
    exports,
    process: { env },
    URL,
    require(name) {
      if (name === "vite") return {
        defineConfig: (value) => value,
        loadEnv(...args) { calls.push(args); return { FRONTEND_PORT: "5200" }; },
      };
      if (name === "@vitejs/plugin-react") return { default: () => ({}) };
      if (name === "node:url") return { fileURLToPath };
      if (name === "node:os") return { devNull };
      throw new Error(`Unexpected config import: ${name}`);
    },
  });
  return { config: exports.default({ mode: "test" }), calls };
}

for (const flag of ["0", "false", "off", "no", " FALSE "]) {
  test(`disabled flag ${JSON.stringify(flag)} skips both root and frontend env`, () => {
    const { config, calls } = evaluate({ COMPETISCOPE_LOAD_ENV_FILES: flag, FRONTEND_PORT: "5188" });
    assert.equal(calls.length, 0);
    assert.equal(config.envDir, devNull);
    assert.equal(config.server.port, 5188);
  });
}

test("default keeps legacy root loading and Vite frontend loading", () => {
  const { config, calls } = evaluate({});
  assert.equal(calls.length, 1);
  assert.equal(config.envDir, undefined);
  assert.equal(config.server.port, 5200);
});

test("explicit profile cache avoids writing frontend node_modules cache", () => {
  const { config } = evaluate({ COMPETISCOPE_LOAD_ENV_FILES: "0", COMPETISCOPE_VITE_CACHE_DIR: "/private/profile/vite-cache" });
  assert.equal(config.cacheDir, "/private/profile/vite-cache");
});

test("installed Vite core cannot read frontend env when loading is disabled", async () => {
  const { resolveConfig } = await import("vite");
  const directory = fs.mkdtempSync(join(tmpdir(), "workbench-vite-env-test-"));
  fs.writeFileSync(join(directory, ".env"), "VITE_ISOLATION_SENTINEL=must-not-be-read\n");
  const originalRead = fs.readFileSync;
  const originalAsyncRead = fs.promises.readFile;
  const reads = [];
  function guard(path) {
    const name = basename(String(path));
    if (name === ".env" || name.startsWith(".env.")) {
      reads.push(String(path));
      throw new Error("env-file read was intercepted before content access");
    }
  }
  fs.readFileSync = function (path, ...args) { guard(path); return originalRead.call(this, path, ...args); };
  fs.promises.readFile = async function (path, ...args) { guard(path); return originalAsyncRead.call(this, path, ...args); };
  try {
    const { config } = evaluate({ COMPETISCOPE_LOAD_ENV_FILES: "0" });
    const resolved = await resolveConfig({ ...config, root: directory, configFile: false }, "serve", "test");
    assert.equal(resolved.envDir, devNull);
    assert.equal(resolved.env.VITE_ISOLATION_SENTINEL, undefined);
    assert.deepEqual(reads, []);
  } finally {
    fs.readFileSync = originalRead;
    fs.promises.readFile = originalAsyncRead;
    fs.rmSync(directory, { recursive: true });
  }
});
