import { spawn } from "child_process";
import { fileURLToPath } from "url";

if (process.argv.includes("--print-timeout")) {
  console.log("llm_timeout_seconds=60");
  console.log("hitl_timeout_seconds=60");
  process.exit(0);
}

const vitestBin = fileURLToPath(new URL("../node_modules/vitest/vitest.mjs", import.meta.url));
const args = [vitestBin, "run", ...process.argv.slice(2)];
const child = spawn(process.execPath, args, {
  stdio: "inherit",
});

child.on("close", (code) => {
  process.exit(code ?? 0);
});
