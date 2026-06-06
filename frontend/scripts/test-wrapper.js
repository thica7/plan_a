import { spawn } from "child_process";

if (process.argv.includes("--print-timeout")) {
  console.log("llm_timeout_seconds=60");
  console.log("hitl_timeout_seconds=60");
  process.exit(0);
}

const args = ["vitest", "run", ...process.argv.slice(2)];
const child = spawn("npx", args, {
  stdio: "inherit",
  shell: true,
});

child.on("close", (code) => {
  process.exit(code ?? 0);
});
