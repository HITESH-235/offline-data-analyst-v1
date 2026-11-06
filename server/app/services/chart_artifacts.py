"""Persisted chart artifacts. Figure JSON is data; HTML is download-only."""
import json
import shutil
import uuid
from pathlib import Path
from app.utils.workspace import get_project_dir


def persist_captures(output_dir, project_id):
    root = Path(output_dir)
    manifest = root / 'captures.json'
    if not manifest.exists():
        return []
    captures = json.loads(manifest.read_text())
    if not project_id:
        return []
    destination = Path(get_project_dir(project_id)) / 'charts'
    destination.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for capture in captures:
        ident = uuid.uuid4().hex
        artifact = {key: capture[key] for key in ('kind', 'title', 'status', 'reason', 'width', 'height') if key in capture}
        artifact.update({'id': ident, 'version': 1})
        files = {}
        for role in ('figure', 'download'):
            filename = capture.get(role)
            if not filename or Path(filename).name != filename:
                continue
            source = root / filename
            if not source.is_file() or source.is_symlink():
                continue
            suffix = source.suffix.lower()
            if suffix not in ('.json', '.html', '.png'):
                continue
            target = destination / f'{ident}-{role}{suffix}'
            shutil.copy2(source, target)
            files[role] = target.name
        if not files:
            continue
        if 'download' not in files and 'figure' in files:
            files['download'] = files['figure']
        if 'download' in files:
            artifact['download_format'] = Path(files['download']).suffix.lstrip('.')
        base = f'/projects/{project_id}/artifacts/{ident}'
        if 'figure' in files:
            artifact['figure_url'] = base + '/figure'
        if 'download' in files:
            artifact['download_url'] = base + '/download'
        if artifact['kind'] == 'png' and 'download' in files:
            artifact['image_url'] = base + '/image'
            artifact['mime_type'] = 'image/png'
        else:
            artifact['mime_type'] = 'application/vnd.plotly.v1+json' if artifact['kind'] == 'plotly' else 'text/html'
        (destination / f'{ident}.artifact.json').write_text(json.dumps({**artifact, 'files': files}))
        artifacts.append(artifact)
    return artifacts


def artifact_file(project_id, artifact_id, role):
    if len(artifact_id) != 32 or any(char not in '0123456789abcdef' for char in artifact_id):
        raise FileNotFoundError('Artifact not found')
    root = (Path(get_project_dir(project_id)) / 'charts').resolve()
    manifest = root / f'{artifact_id}.artifact.json'
    if not manifest.is_file():
        raise FileNotFoundError('Artifact not found')
    meta = json.loads(manifest.read_text())
    lookup = 'download' if role == 'image' and meta['kind'] == 'png' else role
    filename = meta['files'].get(lookup)
    if not filename or Path(filename).name != filename:
        raise FileNotFoundError('Artifact file not found')
    path = root / filename
    if not path.is_file() or path.is_symlink() or path.resolve().parent != root:
        raise FileNotFoundError('Artifact file not found')
    return path, meta


def stage_artifact_deletion(project_id, artifact_ids):
    """Stage only UUID-owned files, restoring them if the DB change fails."""
    from contextlib import contextmanager
    import tempfile

    @contextmanager
    def staged():
        root = Path(get_project_dir(project_id)) / 'charts'
        if not root.is_dir():
            yield
            return
        owned = set()
        for ident in artifact_ids:
            if not isinstance(ident, str) or len(ident) != 32 or any(c not in '0123456789abcdef' for c in ident):
                continue
            # Never follow arbitrary filenames from a manifest into other artifacts.
            owned.add(root / f'{ident}.artifact.json')
            for role in ('figure', 'download'):
                for extension in ('json', 'html', 'png'):
                    owned.add(root / f'{ident}-{role}.{extension}')
        existing = [path for path in owned if path.is_file() or path.is_symlink()]
        if not existing:
            yield
            return
        trash = Path(tempfile.mkdtemp(prefix='.deleting-', dir=root))
        moved = []
        try:
            for path in existing:
                destination = trash / path.name
                path.rename(destination)
                moved.append((path, destination))
            yield
        except BaseException:
            for path, destination in reversed(moved):
                destination.rename(path)
            raise
        finally:
            if trash.exists():
                shutil.rmtree(trash)
    return staged()
