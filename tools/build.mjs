import path from "node:path";
import { repoRoot, pythonPath, runSync } from "./runtime.mjs";

const args = process.argv.slice(2);
const development = args[0] === "dev";
if (development) args.shift();
let libraryRoot = repoRoot;
const rootIndex = args.indexOf("--library-root");
if (rootIndex !== -1) {
  const value = args[rootIndex + 1];
  if (!value || value.startsWith("--")) throw Error("--library-root 需要路径");
  libraryRoot = path.resolve(repoRoot, value);
  args.splice(rootIndex, 2);
}
const forceIndex = args.indexOf("--force");
const force = forceIndex !== -1;
if (force) args.splice(forceIndex, 1);
const python = (command, extra = []) =>
  runSync(pythonPath(), ["tools/models.py", command, ...extra]);
const node = (script, extra = [], options = {}) =>
  runSync(process.execPath, [path.join(repoRoot, script), ...extra], options);

try {
  if (!development && args.length)
    throw Error(`未知构建参数：${args.join(" ")}`);
  python("build", [
    "--library-root",
    libraryRoot,
    ...(force ? ["--force"] : []),
  ]);
  if (development) {
    // The config receives the fixture root without adding Vite CLI options.
    node("node_modules/vite/bin/vite.js", ["--host", "127.0.0.1", ...args], {
      env: { ...process.env, MODEL_LIBRARY_ROOT: libraryRoot },
    });
  } else {
    python("site", ["--library-root", libraryRoot]);
    node("node_modules/typescript/bin/tsc", ["--noEmit"]);
    node("node_modules/vite/bin/vite.js", ["build"]);
    python("publish");
  }
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
