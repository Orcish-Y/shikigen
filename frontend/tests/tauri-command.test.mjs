import assert from "node:assert/strict";
import { createServer as createHttpServer } from "node:http";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { createServer as createViteServer } from "vite";
import { runTauriCommand } from "../scripts/tauri-command.mjs";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));

function createViteFixture(overrides = {}) {
  const lifecycleCalls = [];
  const viteServer = {
    resolvedUrls: { local: ["http://127.0.0.1:5174/"], network: [] },
    async listen() { lifecycleCalls.push("listen"); },
    printUrls() { lifecycleCalls.push("print"); },
    async close() { lifecycleCalls.push("close"); },
    ...overrides,
  };
  return { viteServer, lifecycleCalls };
}

test("desktop dev starts Vite before passing its bound URL and disabling duplicate startup", async () => {
  const { viteServer, lifecycleCalls } = createViteFixture();
  const originalArguments = ["dev", "--no-watch"];
  const previousDevOrigin = process.env.SHIKIGEN_DESKTOP_DEV_ORIGIN;
  const isCommandSuccessful = await runTauriCommand(originalArguments, {
    async createViteServer(options) {
      assert.equal(options.root, frontendRoot);
      lifecycleCalls.push("create");
      return viteServer;
    },
    async invokeTauriCli(cliArguments, commandName) {
      lifecycleCalls.push("invoke");
      assert.equal(commandName, "pnpm tauri");
      assert.equal(process.env.SHIKIGEN_DESKTOP_DEV_ORIGIN, "http://127.0.0.1:5174");
      assert.deepEqual(cliArguments.slice(0, 2), originalArguments);
      assert.equal(cliArguments[2], "--config");
      assert.deepEqual(JSON.parse(cliArguments[3]), {
        build: { devUrl: "http://127.0.0.1:5174/", beforeDevCommand: null },
      });
      return true;
    },
  });
  assert.equal(isCommandSuccessful, true);
  assert.equal(process.env.SHIKIGEN_DESKTOP_DEV_ORIGIN, previousDevOrigin);
  assert.deepEqual(originalArguments, ["dev", "--no-watch"]);
  assert.deepEqual(lifecycleCalls, ["create", "listen", "print", "invoke", "close"]);
});

test("runtime config follows user configs and precedes cargo and app argument separators", async () => {
  const { viteServer } = createViteFixture();
  const originalArguments = ["--verbose", "dev", "--config", "custom.json", "--", "--release", "--", "--help"];
  await runTauriCommand(originalArguments, {
    async createViteServer() { return viteServer; },
    async invokeTauriCli(cliArguments) {
      assert.deepEqual(cliArguments.slice(0, 4), originalArguments.slice(0, 4));
      assert.equal(cliArguments[4], "--config");
      assert.equal(JSON.parse(cliArguments[5]).build.devUrl, "http://127.0.0.1:5174/");
      assert.deepEqual(cliArguments.slice(6), originalArguments.slice(4));
    },
  });
});

test("build, mobile, help, version and other commands never start Vite", async () => {
  for (const cliArguments of [
    [], ["build", "--debug"], ["icon", "logo.svg"], ["android", "dev"],
    ["dev", "--help"], ["-vv", "dev", "-h"], ["dev", "-V"], ["--version"],
  ]) {
    let invocationCount = 0;
    const isCommandSuccessful = await runTauriCommand(cliArguments, {
      async createViteServer() { assert.fail("Vite must not start for this command"); },
      async invokeTauriCli(forwardedArguments) {
        invocationCount += 1;
        assert.equal(forwardedArguments, cliArguments);
        return false;
      },
    });
    assert.equal(isCommandSuccessful, false);
    assert.equal(invocationCount, 1);
  }
});

test("desktop dev closes Vite after a Tauri startup failure", async () => {
  const { viteServer, lifecycleCalls } = createViteFixture();
  const startupError = new Error("cargo failed");
  const previousDevOrigin = process.env.SHIKIGEN_DESKTOP_DEV_ORIGIN;
  await assert.rejects(runTauriCommand(["dev"], {
    async createViteServer() { return viteServer; },
    async invokeTauriCli() { throw startupError; },
  }), (error) => error === startupError);
  assert.equal(process.env.SHIKIGEN_DESKTOP_DEV_ORIGIN, previousDevOrigin);
  assert.deepEqual(lifecycleCalls, ["listen", "print", "close"]);
});

test("the prior development origin is restored after both CLI success and failure", async () => {
  const originalDevOrigin = process.env.SHIKIGEN_DESKTOP_DEV_ORIGIN;
  const priorDevOrigin = "http://127.0.0.1:5199";
  try {
    for (const shouldCliFail of [false, true]) {
      process.env.SHIKIGEN_DESKTOP_DEV_ORIGIN = priorDevOrigin;
      const { viteServer, lifecycleCalls } = createViteFixture();
      const commandPromise = runTauriCommand(["dev"], {
        async createViteServer() { return viteServer; },
        async invokeTauriCli() {
          assert.equal(process.env.SHIKIGEN_DESKTOP_DEV_ORIGIN, "http://127.0.0.1:5174");
          if (shouldCliFail) throw new Error("CLI failure");
          return true;
        },
      });
      if (shouldCliFail) {
        await assert.rejects(commandPromise, /CLI failure/);
      } else {
        assert.equal(await commandPromise, true);
      }
      assert.equal(process.env.SHIKIGEN_DESKTOP_DEV_ORIGIN, priorDevOrigin);
      assert.deepEqual(lifecycleCalls, ["listen", "print", "close"]);
    }
  } finally {
    if (originalDevOrigin === undefined) delete process.env.SHIKIGEN_DESKTOP_DEV_ORIGIN;
    else process.env.SHIKIGEN_DESKTOP_DEV_ORIGIN = originalDevOrigin;
  }
});

test("Vite listen failure closes its resources and never launches Tauri", async () => {
  const { viteServer, lifecycleCalls } = createViteFixture({
    async listen() { throw new Error("bind failed"); },
  });
  await assert.rejects(runTauriCommand(["dev"], {
    async createViteServer() { return viteServer; },
    async invokeTauriCli() { assert.fail("Tauri must not run after a listen failure"); },
  }), /bind failed/);
  assert.deepEqual(lifecycleCalls, ["close"]);
});

test("a missing actual URL closes Vite and refuses to reuse the fixed Tauri URL", async () => {
  const { viteServer, lifecycleCalls } = createViteFixture({ resolvedUrls: null });
  await assert.rejects(runTauriCommand(["dev"], {
    async createViteServer() { return viteServer; },
    async invokeTauriCli() { assert.fail("Tauri must not run without the actual Vite URL"); },
  }), /无法获取前端地址/);
  assert.deepEqual(lifecycleCalls, ["listen", "close"]);
});

test("TAURI_DEV_HOST network address can be forwarded when no local URL is available", async () => {
  const { viteServer } = createViteFixture({
    resolvedUrls: { local: [], network: ["http://192.168.1.10:5175/"] },
  });
  await runTauriCommand(["dev"], {
    async createViteServer() { return viteServer; },
    async invokeTauriCli(cliArguments) {
      assert.equal(JSON.parse(cliArguments.at(-1)).build.devUrl, "http://192.168.1.10:5175/");
    },
  });
});

test("real Vite skips an occupied port, holds the new listener through Tauri, and releases it on exit", { timeout: 20000 }, async () => {
  const occupiedServer = createHttpServer((_request, response) => response.end("existing service"));
  await new Promise((resolve, reject) => {
    occupiedServer.once("error", reject);
    occupiedServer.listen(0, "127.0.0.1", resolve);
  });
  const occupiedPort = occupiedServer.address().port;
  const shouldIgnoreFixtureFile = () => true;
  let viteServer;
  let developmentPort;
  try {
    await runTauriCommand(["dev"], {
      async createViteServer(options) {
        viteServer = await createViteServer({
          ...options,
          // This fixture verifies listener ownership, not file-change HMR.
          // Avoid Vite's asynchronous watcher startup racing fixture teardown.
          server: {
            host: "127.0.0.1",
            port: occupiedPort,
            watch: { ignored: shouldIgnoreFixtureFile },
          },
          logLevel: "silent",
        });
        assert.equal(viteServer.config.server.strictPort, false);
        const fileIgnoreMatchers = [viteServer.config.server.watch.ignored].flat();
        assert.ok(fileIgnoreMatchers.includes(shouldIgnoreFixtureFile));
        assert.equal(shouldIgnoreFixtureFile("tsconfig.json"), true);
        return viteServer;
      },
      async invokeTauriCli(cliArguments) {
        const { build } = JSON.parse(cliArguments.at(-1));
        developmentPort = Number(new URL(build.devUrl).port);
        assert.notEqual(developmentPort, occupiedPort);
        assert.equal(developmentPort, viteServer.httpServer.address().port);
        assert.equal(build.beforeDevCommand, null);
        assert.equal(process.env.SHIKIGEN_DESKTOP_DEV_ORIGIN, new URL(build.devUrl).origin);
        const frontendResponse = await fetch(build.devUrl);
        assert.equal(frontendResponse.status, 200);
        assert.match(await frontendResponse.text(), /\/@vite\/client/);
        assert.equal(await (await fetch(`http://127.0.0.1:${occupiedPort}`)).text(), "existing service");
      },
    });
    assert.equal(viteServer.httpServer.listening, false);
    const replacementServer = createHttpServer();
    try {
      await new Promise((resolve, reject) => {
        replacementServer.once("error", reject);
        replacementServer.listen(developmentPort, "127.0.0.1", resolve);
      });
    } finally {
      await new Promise((resolve) => replacementServer.close(resolve));
    }
  } finally {
    await viteServer?.close();
    await new Promise((resolve) => occupiedServer.close(resolve));
  }
});
