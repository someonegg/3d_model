"""Embed glTF resources without re-exporting scene definitions."""

import base64
import json
import struct
from pathlib import Path
from urllib.parse import unquote, unquote_to_bytes

from .resources import dependencies, resource


def output_file(name):
    return (
        str(Path(name).with_suffix(".glb"))
        if Path(name).suffix.lower() == ".gltf"
        else name
    )


def output_model(model):
    converted = model | {
        "variants": [
            variant | {"file": output_file(variant["file"])}
            for variant in model["variants"]
        ]
    }
    for field in ("artifacts", "publish"):
        if field in model:
            converted[field] = [name if isinstance(name, dict) else output_file(name) for name in model[field]]
    return converted


def pack(directory, filename):
    dependencies(
        directory, filename
    )  # Validate local paths and required extensions first.
    path = resource(directory, filename)
    binary = None
    if path.suffix.lower() == ".gltf":
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        raw = path.read_bytes()
        if len(raw) < 20 or struct.unpack_from("<II", raw, 4) != (2, len(raw)):
            raise ValueError("无效 GLB 文件头")
        cursor, chunks = 12, []
        while cursor < len(raw):
            if cursor + 8 > len(raw):
                raise ValueError("无效 GLB 数据块")
            length, kind = struct.unpack_from("<II", raw, cursor)
            cursor += 8
            if length % 4 or cursor + length > len(raw):
                raise ValueError("无效 GLB 数据块长度")
            chunks.append((kind, raw[cursor : cursor + length]))
            cursor += length
        if (
            not chunks
            or chunks[0][0] != 0x4E4F534A
            or any(kind != 0x004E4942 for kind, _ in chunks[1:])
            or len(chunks) > 2
        ):
            raise ValueError("不支持的 GLB 数据块")
        data = json.loads(chunks[0][1])
        if len(chunks) == 2:
            binary = chunks[1][1]

    def read_uri(uri):
        if uri.startswith("data:"):
            header, payload = uri.split(",", 1)
            return (
                base64.b64decode(unquote_to_bytes(payload), validate=True)
                if header.endswith(";base64")
                else unquote_to_bytes(payload)
            )
        return resource(
            directory, str(Path(filename).parent / unquote(uri))
        ).read_bytes()

    content = bytearray()

    def append(raw):
        offset = len(content)
        content.extend(raw)
        content.extend(b"\0" * (-len(content) % 4))
        return offset

    offsets = []
    buffers = data.get("buffers", [])
    for index, buffer in enumerate(buffers):
        raw = (
            read_uri(buffer["uri"])
            if "uri" in buffer
            else binary
            if index == 0
            else None
        )
        length = buffer["byteLength"]
        if raw is None or length < 0 or len(raw) < length:
            raise ValueError("缓冲区缺失或长度不足")
        offsets.append(append(raw[:length]))
    views = data.setdefault("bufferViews", [])
    for view in views:
        index = view["buffer"]
        offset = view.get("byteOffset", 0)
        if (
            index < 0
            or index >= len(buffers)
            or offset < 0
            or offset + view["byteLength"] > buffers[index]["byteLength"]
        ):
            raise ValueError("bufferView 越界")
        view["byteOffset"] = offsets[index] + offset
        view["buffer"] = 0
    for image in data.get("images", []):
        if "uri" not in image:
            continue
        raw = read_uri(image["uri"])
        mime = (
            "image/png"
            if raw.startswith(b"\x89PNG\r\n\x1a\n")
            else "image/jpeg"
            if raw.startswith(b"\xff\xd8")
            else "image/webp"
            if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
            else None
        )
        if not mime:
            raise ValueError("无法识别纹理格式")
        image["mimeType"] = mime
        image["bufferView"] = len(views)
        views.append({"buffer": 0, "byteOffset": append(raw), "byteLength": len(raw)})
        del image["uri"]
    # Buffer metadata cannot be silently discarded when merging several buffers.
    if len(buffers) > 1 and any(
        set(buffer) - {"uri", "byteLength"} for buffer in buffers
    ):
        raise ValueError("多个缓冲区包含额外元数据，无法无损合并")
    if content:
        merged = dict(buffers[0]) if len(buffers) == 1 else {}
        merged.pop("uri", None)
        merged["byteLength"] = len(content)
        data["buffers"] = [merged]
    else:
        data.pop("buffers", None)
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    encoded += b" " * (-len(encoded) % 4)
    chunks = struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
    if content:
        chunks += struct.pack("<II", len(content), 0x004E4942) + content
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks


def normalize(directory, model):
    converted = output_model(model)
    sources = {variant["file"] for variant in model["variants"]}
    sources.update(model.get("artifacts", []))
    sources.update(n for n in model.get("publish", []) if isinstance(n, str))
    targets = {}
    for source in sorted(sources):
        if Path(source).suffix.lower() not in (".gltf", ".glb"):
            continue
        target = output_file(source)
        if target in targets or (
            source != target and (target in sources or (directory / target).exists())
        ):
            raise ValueError(f"GLB 输出路径冲突：{target}")
        targets[target] = source
    # Read all inputs before writing, including shared dependencies.
    packed = {target: pack(directory, source) for target, source in targets.items()}
    for name, raw in packed.items():
        (directory / name).write_bytes(raw)
    return converted
