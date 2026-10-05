import { runPythonSync } from "./runtime.mjs";
const args = process.argv.slice(2);
try {
  process.exit(
    runPythonSync(
      args[0] === "test"
        ? ["-m", "unittest", "discover", "-s", "tests", ...args.slice(1)]
        : args[0] === "fixtures"
          ? ["tests/generate_fixtures.py"]
          : ["tools/models.py", ...args],
    ),
  );
} catch (error) {
  console.error(error.message);
  process.exit(1);
}
