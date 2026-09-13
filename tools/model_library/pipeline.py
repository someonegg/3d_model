from pathlib import Path
from contextlib import contextmanager
import json
import errno
import os
import shutil
import subprocess
import sys
import tempfile
from .resources import assets, builder_path, digest, discover, resource, input_hashes
from .validation import current_report, inspect_models, finish_validation


TEMP_ROOT = Path(__file__).resolve().parents[2] / 'tmp'


@contextmanager
def publish_workspace(target, prefix):
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=prefix, dir=TEMP_ROOT))
    try:
        yield work
    finally:
        if (work / 'backup').exists() and not target.exists():
            # A second filesystem failure must not delete the only good copy.
            print(f'回滚未完成，保留原目录：{work / "backup"}', file=sys.stderr)
        else:
            shutil.rmtree(work)


def replace_directory(staged, target, backup):
    """Restore the previous directory if publishing raises an exception."""
    devices = {path.stat().st_dev for path in (staged, target.parent, backup.parent)}
    if target.exists():
        devices.add(target.stat().st_dev)
    if len(devices) != 1:
        raise OSError(errno.EXDEV, '输出目录与仓库 tmp/ 不在同一文件系统，无法安全替换目录', str(target))
    existed = target.exists()
    if existed:
        target.replace(backup)
    try:
        staged.replace(target)
    except BaseException:
        if existed:
            backup.replace(target)
        raise


def verifier_path(directory, model):
    if not model.get('verify'):
        return None
    if not model.get('build') or model['verify'] not in model.get('inputs', []):
        raise ValueError('verify 需要 build 且必须声明为 inputs')
    return resource(directory, model['verify'])


def accept(output, directory, model, initial_inputs):
    """Shared acceptance for generated files and copies of existing files."""
    verifier = verifier_path(directory, model)
    reports = inspect_models(output, model)
    if verifier:
        subprocess.run([sys.executable, str(verifier)], cwd=directory,
                       env=dict(os.environ, MODEL_OUTPUT_DIR=str(output), PYTHONDONTWRITEBYTECODE="1"), check=True)
    if input_hashes(directory, model) != initial_inputs:
        raise ValueError('验收期间输入发生变化，请重新构建')
    return finish_validation(output, model, reports, initial_inputs)


def snapshot(directory):
    # Include non-assets too: a directory switch must not discard concurrent edits.
    return {str(p.relative_to(directory)): (os.readlink(p) if p.is_symlink() else digest(p))
            for p in directory.rglob('*') if p.is_file() or p.is_symlink()}


def validate(directory, model):
    directory = directory.resolve()
    builder_path(directory, model)
    initial_inputs = input_hashes(directory, model)
    if initial_inputs:
        previous = json.loads(resource(directory, 'validation.json').read_text(encoding='utf-8'))
        if previous.get('inputs') != initial_inputs:
            raise ValueError('构建输入已改变，请运行 models:build')
    verifier_path(directory, model)
    before = snapshot(directory)
    names = assets(directory, model) - {'validation.json'}
    with publish_workspace(directory, '.model-validate-') as work:
        output = work / 'output'
        output.mkdir()
        for name in sorted(names):
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resource(directory, name), target)
        protected = {name: digest(resource(output, name)) for name in names
                     if name not in model.get('artifacts', [])}
        report = accept(output, directory, model, initial_inputs)
        for name, expected in protected.items():
            if digest(resource(output, name)) != expected:
                raise ValueError(f'专项验收修改了非报告资源：{name}')
        staged = work / 'staged'
        shutil.copytree(directory, staged, symlinks=True)
        for name in ['validation.json', *model.get('artifacts', [])]:
            target = staged / name
            if target.is_symlink() or not target.resolve().is_relative_to(staged.resolve()):
                raise ValueError(f'报告路径越出暂存目录或为符号链接：{name}')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resource(output, name), target)
        if input_hashes(directory, model) != initial_inputs or snapshot(directory) != before:
            raise ValueError('校验期间原始资源或输入发生变化，请重试')
        replace_directory(staged, directory, work / 'backup')
        return report


def build(directory, model):
    builder = builder_path(directory, model)
    verifier_path(directory, model)
    if not builder:
        validate(directory, model)
        return
    directory = directory.resolve()
    initial_inputs = input_hashes(directory, model)
    with publish_workspace(directory, '.model-build-') as work:
        output = work / 'output'
        output.mkdir()
        env = dict(os.environ, MODEL_OUTPUT_DIR=str(output))
        subprocess.run([sys.executable, str(builder)], cwd=directory, env=env, check=True)
        accept(output, directory, model, initial_inputs)
        names = sorted(assets(output, model, generated=True))
        for name in names:
            resource(output, name)
        before = snapshot(directory)
        staged = work / 'staged'
        shutil.copytree(directory, staged, symlinks=True)
        for name in names:
            target = staged / name
            if not target.resolve().is_relative_to(staged.resolve()):
                raise ValueError(f'产物路径越出暂存目录：{name}')
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                raise ValueError(f'产物不能覆盖符号链接：{name}')
            shutil.copy2(output / name, target)
        if input_hashes(directory, model) != initial_inputs or snapshot(directory) != before:
            raise ValueError('构建发布期间原始资源或输入发生变化，请重试')
        replace_directory(staged, directory, work / 'backup')


def catalog(root, strict=False):
    result = []
    for directory, model in discover(root):
        entry = dict(model, base=f'models/{model["id"]}/')
        try:
            entry['validation'] = current_report(directory, model)
        except (ValueError, KeyError, TypeError):
            if strict:
                raise
            entry['validation'] = None
        names = assets(directory, model, strict=strict)
        revisions = {}
        for variant in model['variants']:
            try:
                revisions[variant['file']] = digest(resource(directory, variant['file']))
            except ValueError:
                if strict:
                    raise
                revisions[variant['file']] = 'missing'
        entry['assets'] = sorted(names)
        entry['revisions'] = revisions
        result.append(entry)
    return result


def require_replaceable_site(target):
    if target.exists() and any(target.iterdir()) and not (target / 'catalog.json').is_file():
        raise ValueError('站点输出目录非空且不是已有站点')


def site(root, target):
    root, target = root.resolve(), target.resolve()
    index = catalog(root, strict=True)
    if target == root or target in root.parents:
        raise ValueError('站点输出目录不能覆盖源码目录')
    if any(target == directory or directory.is_relative_to(target) or target.is_relative_to(directory)
           for directory, _ in discover(root)):
        raise ValueError('站点输出目录不能覆盖模型目录')
    require_replaceable_site(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with publish_workspace(target, '.site-build-') as work:
        staged = work / 'staged'
        staged.mkdir()
        for entry in index:
            for name in entry['assets']:
                dest = staged / 'models' / entry['id'] / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(resource(root / entry['id'], name), dest)
        (staged / 'catalog.json').write_text(json.dumps(index, ensure_ascii=False), encoding='utf-8')
        replace_directory(staged, target, work / 'backup')


def publish_site(staged, target):
    """Atomically move a complete staged site into its deployment directory."""
    staged, target = staged.resolve(), target.resolve()
    if not staged.is_dir():
        raise ValueError(f'站点暂存目录不存在：{staged}')
    if staged == target or staged.is_relative_to(target) or target.is_relative_to(staged):
        raise ValueError('站点暂存目录与发布目录不能重叠')
    for name in ('catalog.json', 'index.html'):
        if not (staged / name).is_file():
            raise ValueError(f'站点暂存目录缺少：{name}')
    require_replaceable_site(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with publish_workspace(target, '.site-publish-') as work:
        replace_directory(staged, target, work / 'backup')
