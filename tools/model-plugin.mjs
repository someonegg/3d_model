import { readFile, stat, realpath } from "node:fs/promises";
import path from "node:path";
import { runPython } from "./runtime.mjs";

export function modelLibrary(root) {
  const modelsRoot = path.join(root, "models");
  const outputsRoot = path.join(root, "build/models");
  return {
    name: "model-library",
    configureServer(server) {
      let timer, catalogPromise;
      let closing = false;
      let inputFiles = new Set();
      const getCatalog = () =>
        (catalogPromise ??= runPython([
          "tools/models.py",
          "catalog",
          "--library-root",
          root,
        ])
          .then(async ({ stdout }) => {
            const models = JSON.parse(stdout);
            inputFiles = new Set();
            for (const model of models) {
              const manifest = JSON.parse(
                await readFile(
                  path.join(modelsRoot, model.id, "model.json"),
                  "utf8",
                ),
              );
              inputFiles.add(path.join(modelsRoot, model.id, "model.json"));
              inputFiles.add(
                path.resolve(modelsRoot, model.id, manifest.readme),
              );
              for (const item of manifest.publish ?? []) {
                if (typeof item === "object" && item.from === "source")
                  inputFiles.add(path.resolve(modelsRoot, model.id, item.path));
              }
              if (manifest.bundle) {
                const bundlePath = path.resolve(
                  modelsRoot,
                  model.id,
                  manifest.bundle,
                );
                inputFiles.add(bundlePath);
                const bundle = JSON.parse(await readFile(bundlePath, "utf8"));
                for (const item of bundle.files ?? []) {
                  if (item.from === "source")
                    inputFiles.add(
                      path.resolve(modelsRoot, model.id, item.path),
                    );
                }
              }
              for (const name of manifest.inputs ?? [])
                inputFiles.add(path.resolve(modelsRoot, model.id, name));
            }
            server.watcher.add([...inputFiles]);
            return models;
          })
          .catch((error) => {
            catalogPromise = undefined;
            throw error;
          }));
      const onChange = (_event, file) => {
        if (closing) return;
        const resolved = path.resolve(file);
        const relative = path.relative(modelsRoot, resolved);
        const parts = relative.split(path.sep);
        const discoveryChange =
          resolved === modelsRoot ||
          (!relative.startsWith(".." + path.sep) &&
            !path.isAbsolute(relative) &&
            !parts[0].startsWith(".") &&
            ((parts.length === 1 &&
              (_event === "addDir" || _event === "unlinkDir")) ||
              (parts.length === 2 && parts[1] === "model.json")));
        if (
          !inputFiles.has(resolved) &&
          resolved !== outputsRoot &&
          !resolved.startsWith(outputsRoot + path.sep) &&
          !discoveryChange
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
      };
      const onError = (error) => {
        server.config.logger.error(
          `[model-library] 文件监听失败，正在关闭开发服务：${error.stack ?? error}`,
        );
        if (closing) return;
        closing = true;
        clearTimeout(timer);
        process.exitCode = 1;
        Promise.resolve()
          .then(() => server.close())
          .catch((closeError) => {
            server.config.logger.error(
              `[model-library] 开发服务关闭失败：${closeError.stack ?? closeError}`,
            );
          });
      };
      server.watcher.on("all", onChange);
      server.watcher.on("error", onError);
      server.watcher.add([modelsRoot, outputsRoot]);
      server.httpServer?.once("close", () => {
        closing = true;
        server.watcher.off("all", onChange);
        server.watcher.off("error", onError);
        clearTimeout(timer);
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
          const resourceRoot = path.join(outputsRoot, id);
          const file = await realpath(path.resolve(resourceRoot, name));
          if (!file.startsWith(resourceRoot + path.sep))
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
