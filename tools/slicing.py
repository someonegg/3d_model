"""Shared local Bambu Studio audit helpers; model-specific checks stay in src/."""
from pathlib import Path
import json
import hashlib
import plistlib
import re
import subprocess
import tempfile


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def model_directory(directory):
    directory = Path(directory).resolve()
    return directory.parents[1] / 'build/models' / directory.name


def slicing_workspace(directory, output):
    """Keep manual audit writes away from model sources and published outputs."""
    repo = Path(directory).resolve().parents[1]
    output = Path(output).resolve()
    if output == repo or output in repo.parents or any(
        output.is_relative_to(repo / name) for name in ('models', 'build', 'dist', 'tmp/site')
    ):
        raise ValueError('切片工作区不能覆盖模型源码、构建产物或站点')
    output.mkdir(parents=True, exist_ok=True)
    return output


def source_hashes(source, names):
    source = Path(source).resolve()
    result = {}
    for name in names:
        path = (source / name).resolve()
        if not path.is_relative_to(source) or not path.is_file():
            raise ValueError(f'缺失或越界切片输入：{name}')
        result[name] = sha(path)
    return result


def save_report(output, report, source, inputs):
    """Only commit the local report if the audited source files are unchanged."""
    if source_hashes(source, inputs) != inputs:
        raise ValueError('切片期间模型输入已改变，请重新切片校验')
    report = report | {'source_sha256': inputs}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output,
                                         prefix='.slicing-report-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(Path(output) / 'slicing-validation.json')
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return report


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


def prepare_profiles(root, profiles, process_name, overrides, *, resolver=None):
    resolve = (resolver or resolve_profiles)(profiles)
    data = {'machine': resolve('Bambu Lab P2S 0.4 nozzle'),
            'process': resolve(process_name),
            'filament': resolve('Bambu PLA Basic @BBL P2S')}
    data['process'].update(overrides)
    for name, config in data.items():
        (root / f'{name}.json').write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
    return data


def studio_command(studio, root, output, source, *, arrange):
    return [studio, '--datadir', str(root / 'config'), '--load-settings',
            f'{root}/machine.json;{root}/process.json', '--load-filaments',
            str(root / 'filament.json'), '--arrange', str(arrange), '--orient', '0',
            '--slice', '0', '--export-3mf', 'sliced.3mf', '--outputdir', str(output), str(source)]


def collect_plate(output, source, expected, callback=None):
    import zipfile
    info = json.loads((output / 'result.json').read_text(encoding='utf-8'))
    if info['return_code'] != 0:
        raise RuntimeError(info)
    if len(info['sliced_plates']) != 1:
        raise ValueError('切片必须只包含一个打印盘')
    plate = info['sliced_plates'][0]
    with zipfile.ZipFile(output / 'sliced.3mf') as archive:
        config = json.loads(archive.read('Metadata/project_settings.config'))
        for key, value in {'printer_model': 'Bambu Lab P2S', 'nozzle_diameter': ['0.4'], **expected}.items():
            if config.get(key) != value:
                raise ValueError(f'切片配置不符：{key}')
        gcode = archive.read('Metadata/plate_1.gcode').decode()
        extra = callback(archive, config, gcode, plate, source) if callback else {}
        for name in ('Metadata/plate_1.png', 'Metadata/top_1.png'):
            (output / Path(name).name).write_bytes(archive.read(name))
        (output / 'plate.gcode').write_text(gcode, encoding='utf-8')
    return dict(return_code=0, warning=plate.get('warning_message', ''),
                seconds=plate['total_predication'], filaments=plate['filaments'],
                features=plate['feature_type_times'],
                gcode_sha256=hashlib.sha256(gcode.encode()).hexdigest(), **extra)


def audit_files(studio, root, source, files, inputs, *, arrange, expected,
                callback=None, collect_only=False, runner=None):
    rows, logs = [], []
    for filename in files:
        output = root / Path(filename).stem
        output.mkdir(exist_ok=True)
        print('Slicing ' + filename, flush=True)
        if not collect_only:
            (runner or run_studio)(studio_command(studio, root, output, source / filename,
                                                 arrange=arrange), output)
        logs.append(output / 'studio.log')
        row = collect_plate(output, source / filename, expected, callback)
        rows.append(dict(file=filename, sha256=inputs[filename], **row))
    return {'profile_sha256': {n: sha(root / f'{n}.json') for n in ('machine', 'process', 'filament')},
            'plates': rows, 'physical_print_test': False,
            **studio_metadata(studio, logs, collect_only=collect_only)}
