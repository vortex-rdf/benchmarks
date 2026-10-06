#!/usr/bin/env python3
"""Sample engine memory across named benchmark phases.

A probe returns either one byte count or a cgroup v2 sample mapping with
``current`` (charged total), ``anon`` and ``file``. Each phase keeps the
peak of every reported component; ``peak_rss_bytes`` stays the peak total
so existing summaries read the same field.
"""
from __future__ import annotations

import dataclasses
import threading
from collections.abc import Callable, Mapping
from typing import Any

_COMPONENTS = ('anon', 'file', 'kernel', 'shmem')


@dataclasses.dataclass
class _PhaseMemory:
    first_rss_bytes: int | None = None
    last_rss_bytes: int | None = None
    peak_rss_bytes: int | None = None
    sample_count: int = 0
    component_peaks: dict[str, int] = dataclasses.field(default_factory=dict)

    def add(self, value: int, components: Mapping[str, int] | None = None) -> None:
        if self.first_rss_bytes is None:
            self.first_rss_bytes = value
        self.last_rss_bytes = value
        self.peak_rss_bytes = value if self.peak_rss_bytes is None else max(
            self.peak_rss_bytes, value
        )
        self.sample_count += 1
        for name, component in (components or {}).items():
            self.component_peaks[name] = max(self.component_peaks.get(name, 0), component)

    def to_dict(self) -> dict[str, int | None]:
        output = {
            'first_rss_bytes': self.first_rss_bytes,
            'last_rss_bytes': self.last_rss_bytes,
            'peak_rss_bytes': self.peak_rss_bytes,
            'sample_count': self.sample_count,
        }
        for name in _COMPONENTS:
            if name in self.component_peaks:
                output[f'peak_{name}_bytes'] = self.component_peaks[name]
        return output


class PhaseAwareMemorySampler:
    """Sample one non-negative RSS probe without blocking benchmark work."""

    def __init__(
        self,
        probe: Callable[[], int | None],
        scope: str,
        interval_s: float = 0.01,
    ) -> None:
        if not callable(probe):
            raise TypeError('probe must be callable')
        if not isinstance(scope, str) or not scope:
            raise ValueError('scope must be a non-empty string')
        if interval_s <= 0:
            raise ValueError('interval_s must be greater than zero')
        self._probe = probe
        self._scope = scope
        self._interval_s = interval_s
        self._phase = 'pre_open'
        self._phases: dict[str, _PhaseMemory] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._errors = 0

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError('memory sampler is already started')
        self._sample()
        self._thread = threading.Thread(
            target=self._run, name='krown-rdf-memory-sampler', daemon=True
        )
        self._thread.start()

    def set_phase(self, phase: str) -> None:
        if not isinstance(phase, str) or not phase:
            raise ValueError('phase must be a non-empty string')
        with self._lock:
            self._phase = phase
        self._sample()

    def _sample(self) -> None:
        try:
            value = self._probe()
            if value is None:
                return
            components = None
            if isinstance(value, Mapping):
                components = {
                    name: value[name] for name in _COMPONENTS if name in value
                }
                value = value.get('current')
                if any(not isinstance(item, int) or isinstance(item, bool) or item < 0
                       for item in components.values()):
                    raise ValueError('memory components must be non-negative bytes')
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError('memory probe must return non-negative bytes or None')
            with self._lock:
                self._phases.setdefault(self._phase, _PhaseMemory()).add(
                    value, components
                )
        except (OSError, RuntimeError, TypeError, ValueError):
            with self._lock:
                self._errors += 1

    def _run(self) -> None:
        while not self._stop.wait(self._interval_s):
            self._sample()

    def _snapshot(self, *, sample: bool) -> dict[str, Any]:
        if sample:
            self._sample()
        with self._lock:
            phases = {
                name: value.to_dict()
                for name, value in self._phases.items()
            }
            errors = self._errors
        peaks = [value['peak_rss_bytes'] for value in phases.values()]
        peaks = [value for value in peaks if value is not None]
        component_peaks = {}
        for name in _COMPONENTS:
            values = [phase[f'peak_{name}_bytes'] for phase in phases.values()
                      if f'peak_{name}_bytes' in phase]
            if values:
                component_peaks[f'peak_{name}_bytes'] = max(values)
        lifetime = getattr(self._probe, 'lifetime_peak_bytes', None)
        lifetime_peak = None
        if callable(lifetime):
            try:
                lifetime_peak = lifetime()
            except (OSError, RuntimeError, ValueError):
                lifetime_peak = None
        return {
            **component_peaks,
            'cgroup_lifetime_peak_bytes': lifetime_peak,
            'schema': 'rdf-phase-memory-metrics-v1',
            'scope': self._scope,
            'unit': 'bytes',
            'sampling_interval_ms': self._interval_s * 1000,
            'sample_errors': errors,
            'sample_count': sum(
                value['sample_count'] for value in phases.values()
            ),
            'peak_rss_bytes': max(peaks) if peaks else None,
            'phases': phases,
        }

    def snapshot(self) -> dict[str, Any]:
        """Return a consistent copy without stopping the sampler."""
        if self._thread is None:
            raise RuntimeError('memory sampler is not started')
        return self._snapshot(sample=True)

    def stop(self) -> dict[str, Any]:
        thread = self._thread
        if thread is None:
            raise RuntimeError('memory sampler is not started')
        self._stop.set()
        thread.join(timeout=max(1.0, self._interval_s * 10))
        if thread.is_alive():
            raise RuntimeError('memory sampler thread did not stop')
        return self._snapshot(sample=False)
