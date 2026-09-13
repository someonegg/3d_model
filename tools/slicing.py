"""Shared local Bambu Studio audit helpers; model-specific checks stay in src/."""
from pathlib import Path
import json
import plistlib
import re
import subprocess

from tools.model_library.resources import digest as sha


def resolve_profiles(root):
    index = {}
    for path in sorted(Path(root).rglob('*.json')):
        data = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(data, dict) and 'name' in data:
            index[data['name']] = data

    def resolve(name, stack=()):
        if name in stack:
            raise ValueError(f'配置继承循环：{" -> ".join((*stack, name))}')
        if name not in index:
            raise ValueError(f'缺失切片配置：{name}')
        source = index[name]
        result = {}
        parents = ([source['inherits']] if source.get('inherits') else [])
        parents += source.get('include', [])
        for parent in parents:
            result.update(resolve(parent, (*stack, name)))
        result.update({k: v for k, v in source.items() if k not in ('inherits', 'include')})
        return result

    return resolve


def run_studio(command, output):
    log = Path(output) / 'studio.log'
    with log.open('w', encoding='utf-8') as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=900)
    if result.returncode:
        raise RuntimeError(f'Studio 退出码 {result.returncode}；日志：{log}')


def studio_metadata(studio, logs, *, collect_only=False):
    """Use this invocation's logs, or the invoked macOS bundle's version.

    Collect-only cannot infer the producer version from the currently installed app.
    """
    version = None
    diagnostics = []
    for log in logs:
        text = Path(log).read_text(encoding='utf-8', errors='replace') if Path(log).is_file() else ''
        match = re.search(r'Bambu\s*Studio[^\n\d]*(\d+\.\d+\.\d+(?:\.\d+)?)', text, re.I)
        if match:
            version = match.group(1)
        diagnostics.extend(line.strip() for line in text.splitlines()
                           if re.search(r'\b(error|warning|invalid)\b', line, re.I))
    if version is None and not collect_only:
        info = Path(studio).resolve().parent.parent / 'Info.plist'
        if info.is_file():
            with info.open('rb') as stream:
                data = plistlib.load(stream)
            version = data.get('CFBundleShortVersionString') or data.get('CFBundleVersion')
    return {'software': f'Bambu Studio {version}' if version else 'Bambu Studio (unknown version)',
            'cli_diagnostics': list(dict.fromkeys(diagnostics))}
