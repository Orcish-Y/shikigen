import { runTauriCommand } from "./tauri-command.mjs";

try {
  await runTauriCommand(process.argv.slice(2));
} catch (error) {
  console.error(`[tauri] ${error instanceof Error ? error.message : error}`);
  process.exitCode = 1;
}
