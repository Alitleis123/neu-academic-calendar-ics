"""Stage complete builds and roll back file replacements on write failures."""

import contextlib
import hashlib
import logging
import os
import pathlib
import shutil
import tempfile

LOG = logging.getLogger(__name__)


@contextlib.contextmanager
def locked(output):
    """Hold a nonblocking OS lock for one output directory.

    The lock file stays in the system temp directory. OS locks release even
    when a process crashes; unlinking the file would allow concurrent owners.
    """
    import fcntl

    digest = hashlib.sha256(str(output.resolve()).encode()).hexdigest()[:24]
    path = pathlib.Path(tempfile.gettempdir()) / (".neucal-" + digest + ".lock")
    with path.open("a+b") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another build is already using {}".format(output)) from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def write_atomic(path, data):
    """Write one file beside its destination and replace it atomically."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".neucal-", delete=False) as stream:
            temporary = pathlib.Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o644)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def commit(output, files, *, dry_run=False):
    """Stage every changed file before replacement; restore originals on errors.

    Each file replacement is atomic. Local readers can briefly see mixed files
    during a successful commit; GitHub Pages receives the completed artifact.
    """
    output = pathlib.Path(output)
    changed, unchanged = [], []
    for name, data in sorted(files.items()):
        if pathlib.Path(name).name != name or name in ("", ".", ".."):
            raise ValueError("Unsafe output filename {!r}".format(name))
        path = output / name
        if path.is_symlink():
            raise ValueError("Refusing to replace output symlink: " + str(path))
        if path.exists() and path.read_bytes() == data:
            unchanged.append(name)
        else:
            changed.append(name)
    LOG.info("Publication dry_run=%s changed=%d unchanged=%d", dry_run, len(changed), len(unchanged))
    if dry_run or not changed:
        return {"changed": changed, "unchanged": unchanged}
    created_output = not output.exists()
    output.mkdir(parents=True, exist_ok=True)
    applied = []
    stage = None
    preserve_stage = False
    try:
        stage = pathlib.Path(tempfile.mkdtemp(prefix=".neucal-stage-", dir=output.parent))
        backup = stage / "backup"
        backup.mkdir()
        for name in changed:
            write_atomic(stage / name, files[name])
            if (output / name).exists():
                write_atomic(backup / name, (output / name).read_bytes())
                shutil.copystat(output / name, backup / name)
        try:
            for name in changed:
                os.replace(stage / name, output / name)
                applied.append(name)
        except BaseException as failure:
            # A normal I/O error or Ctrl-C must not leave half a new build.
            errors = []
            for name in reversed(applied):
                try:
                    if (backup / name).exists():
                        os.replace(backup / name, output / name)
                    else:
                        (output / name).unlink()
                except OSError as exc:
                    errors.append("{}: {}".format(name, exc))
            if errors:
                preserve_stage = True
                raise RuntimeError("Rollback incomplete; recovery files retained at {}: {}".format(
                    stage, "; ".join(errors))) from failure
            LOG.error("Rolled back %d file replacements", len(applied))
            raise
    except BaseException:
        if created_output and not any(output.iterdir()):
            output.rmdir()
        raise
    finally:
        if stage is not None and not preserve_stage:
            shutil.rmtree(stage)
    return {"changed": changed, "unchanged": unchanged}
