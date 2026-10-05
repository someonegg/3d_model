import hashlib
import json
import re
import struct
import sys
from importlib import metadata
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DigestCache:
    """Reuse hashes within one operation; re-read files whose metadata changed."""

    def __init__(self):
        self.values = {}

    def __call__(self, path):
        path = path.resolve()
        info = path.stat()
        signature = (
            info.st_dev, info.st_ino, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns,
        )
        previous = self.values.get(path)
        if previous is None or previous[0] != signature:
            previous = (signature, digest(path))
            self.values[path] = previous
        return previous[1]


def resource(directory, name):
    path = (directory / name).resolve()
    if not path.is_relative_to(directory.resolve()) or not path.is_file():
        raise ValueError(f"缺失或越界资源：{name}")
    return path


def input_hashes(directory, model):
    root = directory.resolve().parents[1]
    tools = Path(__file__).resolve().parents[1]
    manifest = json.loads(resource(directory, "model.json").read_text(encoding="utf-8"))
    for field in ('bundle', 'publish', 'readme'):
        manifest.pop(field, None)
    manifest_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    result = {"model.json": manifest_hash}
    # Only shared model execution and acceptance code belongs in every cache.
    # Optional helpers belong in the consuming model's declared inputs.
    for path in [
        tools / "run_model.py",
        *(tools / "model_library" / name for name in (
            "__init__.py", "gltf.py", "building.py", "resources.py",
            "validation.py", "workspace.py",
        )),
    ]:
        result[f"@tools/{path.relative_to(tools)}"] = digest(path)
    requirements = tools.parent / "requirements.txt"
    result["@environment/requirements.txt"] = digest(requirements)
    result["@environment/python"] = sys.version
    for line in requirements.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", line)
        if name is None:
            raise ValueError(f"无效依赖声明：{line}")
        package = name.group()
        result[f"@environment/package/{package}"] = metadata.version(package)
    names = model.get("inputs", [])
    if not isinstance(names, list) or any(
        not isinstance(name, str) or not name or Path(name).is_absolute()
        for name in names
    ):
        raise ValueError("无效构建输入列表")
    for name in names:
        path = (directory / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"缺失或越界构建输入：{name}")
        result[name] = digest(path)
    return result


def builder_path(directory, model):
    if "build" not in model:
        raise ValueError("模型必须声明 build")
    name = model["build"]
    inputs = model.get("inputs", [])
    if (
        not isinstance(name, str)
        or not name
        or Path(name).is_absolute()
        or ".." in Path(name).parts
        or not isinstance(inputs, list)
        or name not in inputs
    ):
        raise ValueError("build 必须是模型目录内的脚本，且声明在 inputs 中")
    return resource(directory, name)


def variant_config(model, variant):
    """Resolve and validate the configuration used for this file."""
    config = {
        key: variant.get(key, model.get(key)) for key in ("purpose", "units", "up")
    }
    filename = variant.get("file")
    if (
        not isinstance(filename, str)
        or not filename
        or Path(filename).is_absolute()
        or ".." in Path(filename).parts
    ):
        raise ValueError("无效变体文件路径")
    suffix = Path(filename).suffix.lower()
    if suffix not in (".stl", ".glb", ".gltf"):
        raise ValueError("仅支持 STL、GLB 和 glTF")
    if config["purpose"] not in ("print", "display"):
        raise ValueError("无效变体用途")
    if suffix == ".stl" and (
        config["units"] not in ("mm", "cm", "m") or config["up"] not in ("Y", "Z")
    ):
        raise ValueError("STL 必须声明 units 和 up")
    if suffix in (".glb", ".gltf") and (config["units"] != "m" or config["up"] != "Y"):
        raise ValueError("GLB/glTF 必须使用 m 单位、Y 向上")
    if config["purpose"] == "print" and suffix != ".stl":
        raise ValueError("打印校验仅支持 STL；请将 GLB/glTF 变体登记为展示用途")
    return config


def discover(root):
    models = []
    models_root = root / "models"
    if not models_root.is_dir():
        raise ValueError(f"模型库目录不存在：{models_root}")
    for directory in sorted(models_root.iterdir()):
        if directory.name.startswith(".") or not directory.is_dir():
            continue
        path = directory / "model.json"
        if not path.is_file():
            raise ValueError(f"模型目录缺少 model.json：{directory}")
        model = json.loads(path.read_text(encoding="utf-8"))
        if model.get("id") != path.parent.name or model.get("purpose") not in (
            "print",
            "display",
        ):
            raise ValueError(f"无效模型 ID 或用途：{path}")
        if not model.get("variants") or len(
            {v["id"] for v in model["variants"]}
        ) != len(model["variants"]):
            raise ValueError(f"无效变体：{path}")
        for key in ("preview", "readme"):
            name = model.get(key)
            if (
                not isinstance(name, str)
                or not name
                or Path(name).is_absolute()
                or ".." in Path(name).parts
            ):
                raise ValueError(f"无效资源路径：{key}")
        if 'assembly' in model:
            name = model['assembly']
            if (not isinstance(name, str) or not name.endswith('.glb')
                    or Path(name).is_absolute() or '..' in Path(name).parts
                    or name not in model.get('artifacts', [])
                    or name not in model.get('publish', [])):
                raise ValueError('assembly 必须是 artifacts 和 publish 中的 GLB')
        builder_path(path.parent, model)
        if "verify" in model:
            name = model["verify"]
            if (
                not isinstance(name, str)
                or not name
                or Path(name).is_absolute()
                or ".." in Path(name).parts
                or not model.get("build")
                or name not in model.get("inputs", [])
            ):
                raise ValueError(
                    "verify 必须是模型目录内的脚本，且声明 build 和对应 inputs"
                )
            resource(path.parent, name)
        for field in ("artifacts", "publish"):
            if not isinstance(model.get(field, []), list):
                raise ValueError(f"无效资源列表：{field}")
        for item in model.get("publish", []):
            name = item.get("path") if isinstance(item, dict) else item
            if (
                not isinstance(name, str)
                or Path(name).suffix.lower()
                not in {
                    ".stl",
                    ".glb",
                    ".gltf",
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".webp",
                    ".svg",
                    ".md",
                    ".pdf",
                    ".zip",
                }
                or any(
                    part in {"src", "source", "references"} for part in Path(name).parts
                )
            ):
                raise ValueError("publish 仅允许用户模型、预览和说明")
        artifacts = model.get("artifacts", [])
        if not isinstance(artifacts, list) or any(
            not isinstance(name, str)
            or not name
            or Path(name).is_absolute()
            or ".." in Path(name).parts
            for name in artifacts
        ):
            raise ValueError("无效附加产物路径")
        for variant in model["variants"]:
            variant_config(model, variant)
        from .bundling import configuration

        configuration(path.parent, model)
        models.append((path.parent, model))
    identifiers = {m["id"] for _, m in models}
    for _, model in models:
        deps = model.get("depends_on", [])
        if not isinstance(deps, list) or any(
            not isinstance(d, str) or d not in identifiers for d in deps
        ):
            raise ValueError("无效模型依赖")
    return models


def output_directory(directory):
    return directory.resolve().parents[1] / "build/models" / directory.name


def build_order(models):
    pending = {model["id"]: (directory, model) for directory, model in models}
    ordered, active, done = [], set(), set()

    def visit(identifier):
        if identifier in active:
            raise ValueError("模型构建依赖循环")
        if identifier in done:
            return
        active.add(identifier)
        directory, model = pending[identifier]
        for dependency in model.get("depends_on", []):
            if dependency not in pending:
                raise ValueError("无效模型依赖")
            visit(dependency)
        active.remove(identifier)
        done.add(identifier)
        ordered.append((directory, model))

    for identifier in pending:
        visit(identifier)
    return ordered


def dependencies(directory, filename):
    path = resource(directory, filename)
    result = {filename}
    if path.suffix.lower() in (".gltf", ".glb"):
        if path.suffix.lower() == ".gltf":
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            raw = path.read_bytes()
            if len(raw) < 20 or raw[:4] != b"glTF" or raw[16:20] != b"JSON":
                raise ValueError("无效 GLB 文件")
            length = struct.unpack("<I", raw[12:16])[0]
            data = json.loads(raw[20 : 20 + length])
        for item in data.get("buffers", []) + data.get("images", []):
            uri = item.get("uri", "")
            if uri and not uri.startswith("data:"):
                from urllib.parse import unquote

                if ":" in uri or uri.startswith("/"):
                    raise ValueError("glTF 仅支持本地依赖")
                dep = resource(directory, str(Path(filename).parent / unquote(uri)))
                result.add(str(dep.relative_to(directory.resolve())))
        unsupported = set(data.get("extensionsRequired", [])) & {
            "KHR_draco_mesh_compression",
            "EXT_meshopt_compression",
            "KHR_texture_basisu",
        }
        if unsupported:
            raise ValueError(f"不支持的压缩扩展：{unsupported}")
    return result


def generated_assets(directory, model):
    """Declared build outputs, including internal acceptance reports."""
    names = {
        "validation.json",
        model["preview"],
        *model.get("artifacts", []),
        *(n for n in model.get("publish", []) if isinstance(n, str)),
    }
    for variant in model["variants"]:
        names.add(variant["file"])
        names.update(dependencies(directory, variant["file"]))
    names -= set(model.get("bundle_outputs", []))
    return names


def published_assets(directory, model, strict=True):
    from .gltf import output_model

    model = output_model(model)
    names = {model["preview"], model["readme"], *(n["path"] if isinstance(n, dict) else n for n in model.get("publish", []))}
    for variant in model["variants"]:
        names.add(variant["file"])
        try:
            names.update(dependencies(output_directory(directory), variant["file"]))
        except ValueError:
            if strict:
                raise
    return names


def published_resource(directory, model, name):
    return resource(output_directory(directory), name)
