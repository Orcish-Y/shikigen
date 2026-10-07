import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));

async function invokeNativeTauriCli(cliArguments, commandName) {
  const { default: tauriCli } = await import("@tauri-apps/cli");
  return tauriCli.run(cliArguments, commandName);
}

/** Start the owned Vite listener before passing its actual URL to Tauri. */
export async function runTauriCommand(
  tauriArguments,
  {
    createViteServer = createServer,
    invokeTauriCli = invokeNativeTauriCli,
  } = {},
) {
  const separatorIndex = tauriArguments.indexOf("--");
  const cliEndIndex = separatorIndex < 0 ? tauriArguments.length : separatorIndex;
  const cliArguments = tauriArguments.slice(0, cliEndIndex);
  const command = cliArguments.find(
    (argument) => !/^(-v+|--verbose)$/.test(argument),
  );
  const isHelpOrVersionRequest = cliArguments.some((argument) =>
    ["-h", "--help", "-V", "--version"].includes(argument),
  );

  if (command !== "dev" || isHelpOrVersionRequest) {
    return invokeTauriCli(tauriArguments, "pnpm tauri");
  }

  const viteServer = await createViteServer({ root: frontendRoot });
  const previousDevOrigin = process.env.SHIKIGEN_DESKTOP_DEV_ORIGIN;
  try {
    await viteServer.listen();
    const devUrl = viteServer.resolvedUrls?.local[0]
      ?? viteServer.resolvedUrls?.network[0];
    if (!devUrl) {
      throw new Error("Vite 已启动，但无法获取前端地址");
    }
    viteServer.printUrls();
    // Inherited by the managed Python backend, whose CORS policy must match.
    process.env.SHIKIGEN_DESKTOP_DEV_ORIGIN = new URL(devUrl).origin;

    // Keep the listener bound: probing and releasing a port creates a race.
    // The final override also disables Tauri's duplicate beforeDevCommand.
    const developmentConfig = JSON.stringify({
      build: { devUrl, beforeDevCommand: null },
    });
    const developmentArguments = [
      ...cliArguments,
      "--config",
      developmentConfig,
      ...tauriArguments.slice(cliEndIndex),
    ];
    return await invokeTauriCli(developmentArguments, "pnpm tauri");
  } finally {
    if (previousDevOrigin === undefined) {
      delete process.env.SHIKIGEN_DESKTOP_DEV_ORIGIN;
    } else {
      process.env.SHIKIGEN_DESKTOP_DEV_ORIGIN = previousDevOrigin;
    }
    await viteServer.close();
  }
}
