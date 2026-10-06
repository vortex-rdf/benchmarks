#!/usr/bin/env python3
"""Measure engine memory from cgroup v2 files without spawning processes.

Every measured engine runs in its own cgroup: Docker containers in the
cgroup Docker creates, and local workers in a child cgroup of the delegated
systemd scope that the campaign creates for each system. Samples report the
charged total (``memory.current``) and its anonymous and file-backed parts
(``memory.stat``) separately.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path, PurePosixPath

CGROUP_ROOT = Path('/sys/fs/cgroup')
PROC_ROOT = Path('/proc')
SAMPLE_SCHEMA = 'cgroup-v2-memory-sample-v1'
_STAT_FIELDS = ('anon', 'file', 'kernel', 'shmem')
_SAFE_NAME = re.compile(r'^[A-Za-z0-9._-]+$')


def cgroup_path_of_pid(pid: int, *, cgroup_root: Path = CGROUP_ROOT,
                       proc_root: Path = PROC_ROOT) -> Path:
    """Return the cgroup v2 directory that contains one live process."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise ValueError('pid must be a positive integer')
    lines = (proc_root / str(pid) / 'cgroup').read_text(encoding='utf-8').splitlines()
    matches = [line.split(':', 2)[2] for line in lines if line.startswith('0::')]
    if len(matches) != 1:
        raise RuntimeError('process has no unique cgroup v2 membership')
    relative = PurePosixPath(matches[0])
    if not relative.is_absolute() or '..' in relative.parts:
        raise RuntimeError('process cgroup path is invalid')
    return cgroup_root / relative.relative_to('/')


class CgroupMemoryReader:
    """Read one cgroup's current, anonymous, and file-backed memory."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def sample(self) -> dict[str, int] | None:
        """Return one sample, or None when the cgroup no longer exists."""
        try:
            current = int((self.path / 'memory.current').read_text(encoding='ascii'))
            stat_text = (self.path / 'memory.stat').read_text(encoding='ascii')
        except FileNotFoundError:
            return None
        sample = {'current': current}
        for line in stat_text.splitlines():
            key, _, value = line.partition(' ')
            if key in _STAT_FIELDS:
                sample[key] = int(value)
        if 'anon' not in sample or 'file' not in sample:
            raise RuntimeError(f'memory.stat lacks anon or file: {self.path}')
        return sample

    __call__ = sample

    def lifetime_peak_bytes(self) -> int | None:
        """Return memory.peak (the cgroup lifetime maximum), if available."""
        try:
            return int((self.path / 'memory.peak').read_text(encoding='ascii'))
        except FileNotFoundError:
            return None


def _docker_container_pid(container: str) -> int | None:
    result = subprocess.run(
        ['docker', 'container', 'inspect', '--format', '{{.State.Pid}}', container],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    if not value.isdigit():
        raise RuntimeError('Docker returned an invalid container PID')
    pid = int(value)
    return pid if pid > 0 else None


class ContainerCgroupMemory:
    """Sample a container cgroup; resolve it through Docker only when needed.

    Docker is asked for the PID once per container start. A sample after the
    container disappears triggers at most one re-resolution per interval, so
    the sampler never runs ``docker inspect`` at its sampling rate.
    """

    def __init__(self, container: str, *, resolve_interval_s: float = 1.0,
                 pid_lookup=_docker_container_pid,
                 cgroup_root: Path = CGROUP_ROOT, proc_root: Path = PROC_ROOT):
        if not isinstance(container, str) or not container.strip():
            raise ValueError('container must be a non-empty string')
        self.container = container
        self._resolve_interval_s = resolve_interval_s
        self._pid_lookup = pid_lookup
        self._cgroup_root = cgroup_root
        self._proc_root = proc_root
        self._reader: CgroupMemoryReader | None = None
        self._last_resolve = float('-inf')
        self.resolve_count = 0

    def _resolve(self) -> CgroupMemoryReader | None:
        now = time.monotonic()
        if now - self._last_resolve < self._resolve_interval_s:
            return None
        self._last_resolve = now
        self.resolve_count += 1
        pid = self._pid_lookup(self.container)
        if pid is None:
            return None
        try:
            path = cgroup_path_of_pid(pid, cgroup_root=self._cgroup_root,
                                      proc_root=self._proc_root)
        except FileNotFoundError:
            return None
        self._reader = CgroupMemoryReader(path)
        return self._reader

    def sample(self) -> dict[str, int] | None:
        reader = self._reader or self._resolve()
        if reader is None:
            return None
        value = reader.sample()
        if value is None:
            self._reader = None
            reader = self._resolve()
            value = None if reader is None else reader.sample()
        return value

    __call__ = sample

    def lifetime_peak_bytes(self) -> int | None:
        return None if self._reader is None else self._reader.lifetime_peak_bytes()


class DelegatedCgroupWorkspace:
    """Create child cgroups for local workers inside a delegated scope.

    cgroup v2 forbids processes in a cgroup that distributes controllers to
    children, so the harness first moves itself into ``harness``. Workers
    then start in their own child cgroup, which isolates their memory from
    the harness while the scope limit and kill still cover both.
    """

    def __init__(self, scope: Path):
        self.scope = Path(scope)
        self.harness = self.scope / 'harness'

    @classmethod
    def for_current_process(cls, *, cgroup_root: Path = CGROUP_ROOT,
                            proc_root: Path = PROC_ROOT) -> 'DelegatedCgroupWorkspace':
        own = cgroup_path_of_pid(os.getpid(), cgroup_root=cgroup_root,
                                 proc_root=proc_root)
        scope = own.parent if own.name == 'harness' else own
        workspace = cls(scope)
        workspace._prepare()
        return workspace

    def _prepare(self) -> None:
        controllers = (self.scope / 'cgroup.controllers').read_text(encoding='ascii').split()
        if 'memory' not in controllers:
            raise RuntimeError(f'memory controller is unavailable in {self.scope}')
        if not os.access(self.scope / 'cgroup.subtree_control', os.W_OK):
            raise RuntimeError(
                f'cgroup is not delegated: {self.scope}; run the system inside '
                'systemd-run --user --scope -p Delegate=yes'
            )
        self.harness.mkdir(exist_ok=True)
        # Move every process, including the harness itself, out of the scope root.
        for line in (self.scope / 'cgroup.procs').read_text(encoding='ascii').split():
            try:
                (self.harness / 'cgroup.procs').write_text(line, encoding='ascii')
            except ProcessLookupError:
                continue
        enabled = (self.scope / 'cgroup.subtree_control').read_text(encoding='ascii').split()
        if 'memory' not in enabled:
            (self.scope / 'cgroup.subtree_control').write_text('+memory', encoding='ascii')

    def create(self, name: str) -> Path:
        """Create one fresh, empty worker cgroup and return its path."""
        if not _SAFE_NAME.fullmatch(name) or name == 'harness':
            raise ValueError(f'invalid worker cgroup name: {name!r}')
        path = self.scope / name
        if path.exists():
            self.remove(path)
        path.mkdir()
        return path

    @staticmethod
    def remove(path: Path) -> None:
        """Remove an empty worker cgroup; leave it in place if still populated."""
        try:
            path.rmdir()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    @staticmethod
    def launch_prefix(path: Path) -> list[str]:
        """Return argv that joins ``path`` before exec, so no memory escapes it."""
        return ['/bin/sh', '-c', 'echo $$ > "$0/cgroup.procs" && exec "$@"', str(path)]
