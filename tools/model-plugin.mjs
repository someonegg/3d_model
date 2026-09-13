import { readFile, stat, readdir, realpath } from "node:fs/promises";
import path from "node:path";
import { watch } from "node:fs";
import { runPython } from "./runtime.mjs";

const ignored = (name) => name.startsWith(".");

export function modelLibrary(root) {
  const modelsRoot = path.join(root, "models");
  return {
    name: "model-library",
    configureServer(server) {
      let timer, catalogPromise;
      let inputFiles = new Set();
      const getCatalog = () =>
        (catalogPromise ??= runPython([
          "tools/models.py",
          "catalog",
          "--model-root",
          root,
        ])
          .then(({ stdout }) => {
            const models = JSON.parse(stdout);
            inputFiles = new Set(
              models.flatMap((model) =>
                (model.inputs ?? []).map((name) =>
                  path.resolve(modelsRoot, model.id, name),
                ),
              ),
            );
            server.watcher.add([...inputFiles]);
            return models;
          })
          .catch((error) => {
            catalogPromise = undefined;
            throw error;
          }));
      const watchModels = async () => {
        for (const entry of await readdir(modelsRoot, {
          withFileTypes: true,
        })) {
          if (entry.isDirectory() && !ignored(entry.name))
            server.watcher.add(path.join(modelsRoot, entry.name));
        }
      };
      void watchModels();
      const rootWatcher = watch(modelsRoot, () => {
        void watchModels();
      });
      server.httpServer?.once("close", () => {
        rootWatcher.close();
        clearTimeout(timer);
      });
      server.watcher.on("all", (_event, file) => {
        const relative = path.relative(modelsRoot, file);
        if (
          !inputFiles.has(path.resolve(file)) &&
          (relative.startsWith("..") ||
            ignored(relative.split(path.sep)[0]) ||
            relative
              .split(path.sep)
              .some((part) => part.startsWith(".") || part === "__pycache__") ||
            file.endsWith(".tmp"))
        )
          return;
        catalogPromise = undefined;
        clearTimeout(timer);
        timer = setTimeout(
          () =>
            server.ws.send({
              type: "custom",
              event: "models-updated",
              data: {},
            }),
          500,
        );
      });
      server.middlewares.use(async (req, res, next) => {
        const pathname = new URL(req.url, "http://localhost").pathname;
        if (pathname !== "/catalog.json" && !pathname.startsWith("/models/"))
          return next();
        try {
          const models = await getCatalog();
          res.setHeader("Cache-Control", "no-store");
          if (pathname === "/catalog.json") {
            res.setHeader("Content-Type", "application/json");
            return res.end(JSON.stringify(models));
          }
          const [, , id, ...segments] = decodeURIComponent(pathname).split("/");
          const model = models.find((m) => m.id === id);
          if (!model) throw Error("未知模型");
          const name = segments.join("/");
          const allowed = new Set(model.assets);
          if (!allowed.has(name)) throw Error("未声明资源");
          const file = await realpath(path.resolve(modelsRoot, id, name));
          if (!file.startsWith(path.join(modelsRoot, id) + path.sep))
            throw Error("无效路径");
          const info = await stat(file);
          res.setHeader("Content-Length", info.size);
          res.setHeader(
            "Content-Type",
            {
              ".json": "application/json",
              ".gltf": "model/gltf+json",
              ".glb": "model/gltf-binary",
              ".png": "image/png",
              ".jpg": "image/jpeg",
              ".md": "text/plain; charset=utf-8",
            }[path.extname(file).toLowerCase()] ?? "application/octet-stream",
          );
          res.end(await readFile(file));
        } catch (error) {
          res.statusCode = 404;
          res.end(String(error));
        }
      });
    },
  };
}
