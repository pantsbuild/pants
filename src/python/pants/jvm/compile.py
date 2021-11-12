# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from abc import ABCMeta
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Iterable, Iterator, Sequence

from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.fs import Digest
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import CoarsenedTarget, FieldSet
from pants.engine.unions import UnionMembership, union
from pants.jvm.resolve.key import CoursierResolveKey
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import strip_v2_chroot_path

logger = logging.getLogger(__name__)


class ClasspathSourceMissing(Exception):
    """No compiler instances were compatible with a CoarsenedTarget."""


class ClasspathSourceAmbiguity(Exception):
    """Too many compiler instances were compatible with a CoarsenedTarget."""


@union
@dataclass(frozen=True)
class ClasspathEntryRequest(metaclass=ABCMeta):
    """A request for a ClasspathEntry for the given CoarsenedTarget and resolve.

    TODO: Move to `classpath.py`.
    """

    component: CoarsenedTarget
    resolve: CoursierResolveKey

    # The FieldSets types that this request subclass is compatible with. A request will only be
    # constructed if it is compatible with _all_ of the members of the CoarsenedTarget.
    field_sets: ClassVar[tuple[type[FieldSet], ...]]

    @staticmethod
    def for_targets(
        union_membership: UnionMembership, component: CoarsenedTarget, resolve: CoursierResolveKey
    ) -> ClasspathEntryRequest:
        """Constructs a subclass compatible with the members of the CoarsenedTarget."""
        compatible = []
        impls = union_membership.get(ClasspathEntryRequest)
        for impl in impls:
            if all(any(fs.is_applicable(t) for fs in impl.field_sets) for t in component.members):
                compatible.append(impl)

        if len(compatible) == 1:
            return compatible[0](component, resolve)

        impls_str = ", ".join(sorted(impl.__name__ for impl in impls))
        targets_str = "\n  ".join(
            sorted(f"{t.address.spec}\t({type(t).alias})" for t in component.members)
        )
        if compatible:
            raise ClasspathSourceAmbiguity(
                f"More than one JVM compiler instance ({impls_str}) was compatible with "
                f"the inputs:\n  {targets_str}"
            )
        else:
            raise ClasspathSourceMissing(
                f"No single JVM compiler instance (from: {impls_str}) was compatible with all of the "
                f"the inputs:\n  {targets_str}"
            )


@frozen_after_init
@dataclass(unsafe_hash=True)
class ClasspathEntry:
    """A JVM classpath entry represented as a series of JAR files, and their dependencies.

    This is a series of JAR files in order to account for "exported" dependencies, when a node
    and some of its dependencies are indistinguishable (such as for aliases, or potentially
    explicitly declared or inferred `exported=` lists in the future).

    This class additionally keeps filenames in order to preserve classpath ordering for the
    `classpath_arg` method: although Digests encode filenames, they are stored sorted.

    TODO: Move to `classpath.py`.
    TODO: Generalize via https://github.com/pantsbuild/pants/issues/13112.
    """

    digest: Digest
    filenames: tuple[str, ...]
    dependencies: FrozenOrderedSet[ClasspathEntry]

    def __init__(
        self,
        digest: Digest,
        filenames: Iterable[str] = (),
        dependencies: Iterable[ClasspathEntry] = (),
    ):
        self.digest = digest
        self.filenames = tuple(filenames)
        self.dependencies = FrozenOrderedSet(dependencies)

    @classmethod
    def merge(cls, digest: Digest, entries: Iterable[ClasspathEntry]) -> ClasspathEntry:
        """After merging the Digests for entries, merge their filenames and dependencies."""
        return cls(
            digest,
            (f for cpe in entries for f in cpe.filenames),
            (d for cpe in entries for d in cpe.dependencies),
        )

    @classmethod
    def arg(cls, entries: Iterable[ClasspathEntry], *, prefix: str = "") -> str:
        """Builds the non-recursive classpath arg for the given entries.

        To construct a recursive classpath arg, first expand the entries with `cls.closure()`.
        """
        return ":".join(os.path.join(prefix, f) for cpe in entries for f in cpe.filenames)

    @classmethod
    def closure(cls, roots: Iterable[ClasspathEntry]) -> Iterator[ClasspathEntry]:
        """All ClasspathEntries reachable from the given roots."""

        visited = set()
        queue = deque(roots)
        while queue:
            ct = queue.popleft()
            if ct in visited:
                continue
            visited.add(ct)
            yield ct
            queue.extend(ct.dependencies)

    def __repr__(self):
        return f"ClasspathEntry({self.filenames}, dependencies={len(self.dependencies)})"

    def __str__(self) -> str:
        return repr(self)


class CompileResult(Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEPENDENCY_FAILED = "dependency failed"


@dataclass(frozen=True)
class FallibleClasspathEntry(EngineAwareReturnType):
    description: str
    result: CompileResult
    output: ClasspathEntry | None
    exit_code: int
    stdout: str | None = None
    stderr: str | None = None

    @classmethod
    def from_fallible_process_result(
        cls,
        description: str,
        process_result: FallibleProcessResult,
        output: ClasspathEntry | None,
        *,
        strip_chroot_path: bool = False,
    ) -> FallibleClasspathEntry:
        def prep_output(s: bytes) -> str:
            return strip_v2_chroot_path(s) if strip_chroot_path else s.decode()

        exit_code = process_result.exit_code
        # TODO: Coursier renders this line on macOS.
        stderr = "\n".join(
            line
            for line in prep_output(process_result.stderr).splitlines()
            if line != "setrlimit to increase file descriptor limit failed, errno 22"
        )
        return cls(
            description=description,
            result=(CompileResult.SUCCEEDED if exit_code == 0 else CompileResult.FAILED),
            output=output,
            exit_code=exit_code,
            stdout=prep_output(process_result.stdout),
            stderr=stderr,
        )

    @classmethod
    def if_all_succeeded(
        cls, fallible_classpath_entries: Sequence[FallibleClasspathEntry]
    ) -> tuple[ClasspathEntry, ...] | None:
        """If all given FallibleClasspathEntries succeeded, return them as ClasspathEntries."""
        classpath_entries = tuple(fcc.output for fcc in fallible_classpath_entries if fcc.output)
        if len(classpath_entries) != len(fallible_classpath_entries):
            return None
        return classpath_entries

    def level(self) -> LogLevel:
        return LogLevel.ERROR if self.result == CompileResult.FAILED else LogLevel.DEBUG

    def message(self) -> str:
        message = self.description
        message += (
            " succeeded." if self.exit_code == 0 else f" failed (exit code {self.exit_code})."
        )
        if self.stdout:
            message += f"\n{self.stdout}"
        if self.stderr:
            message += f"\n{self.stderr}"
        return message

    def cacheable(self) -> bool:
        # Failed compile outputs should be re-rendered in every run.
        return self.exit_code == 0


@rule
def required_classfiles(fallible_result: FallibleClasspathEntry) -> ClasspathEntry:
    if fallible_result.result == CompileResult.SUCCEEDED:
        assert fallible_result.output
        return fallible_result.output
    # NB: The compile outputs will already have been streamed as FallibleClasspathEntries finish.
    raise Exception(
        f"Compile failed:\nstdout:\n{fallible_result.stdout}\nstderr:\n{fallible_result.stderr}"
    )


def rules():
    return collect_rules()
