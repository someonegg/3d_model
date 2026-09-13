import { execFile, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { promisify } from "node:util";

export const repoRoot = fileURLToPath(new URL("../", import.meta.url));
export function pythonPath() {
  const executable = path.join(
    repoRoot,
    process.platform === "win32"
      ? ".venv/Scripts/python.exe"
      : ".venv/bin/python",
  );
  if (!existsSync(executable))
    throw Error("请先执行 python3 -m venv .venv，再安装 requirements.txt");
  return executable;
}
export function runPython(args) {
  return promisify(execFile)(pythonPath(), args, {
    cwd: repoRoot,
    maxBuffer: 8 * 1024 * 1024,
  });
}
export function runPythonSync(args) {
  const result = spawnSync(pythonPath(), args, {
    cwd: repoRoot,
    stdio: "inherit",
  });
  if (result.error) throw result.error;
  return result.status ?? 1;
}
