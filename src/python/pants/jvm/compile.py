# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from abc import ABCMeta
from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
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


class ClasspathRootOnlyWasInner(Exception):
    """A root_only request type was used as an inner node in a compile graph."""


class _ClasspathEntryRequestClassification(Enum):
    COMPATIBLE = auto()
    PARTIAL = auto()
    CONSUME_ONLY = auto()
    INCOMPATIBLE = auto()


@union
@dataclass(frozen=True)
class ClasspathEntryRequest(metaclass=ABCMeta):
    """A request for a ClasspathEntry for the given CoarsenedTarget and resolve.

    TODO: Move to `classpath.py`.
    """

    component: CoarsenedTarget
    resolve: CoursierResolveKey
    # If this request contains some FieldSets which do _not_ match this request class's
    # FieldSets a prerequisite request will be set. When set, the provider of the
    # ClasspathEntry should recurse with this request first, and include it as a dependency.
    prerequisite: ClasspathEntryRequest | None = None

    # The FieldSet types that this request subclass can produce a ClasspathEntry for. A request
    # will only be constructed if it is compatible with all of the members of the CoarsenedTarget,
    # or if a `prerequisite` request will provide an entry for the rest of the members.
    field_sets: ClassVar[tuple[type[FieldSet], ...]]

    # Additional FieldSet types that this request subclass may consume (but not produce a
    # ClasspathEntry for) iff they are contained in a component with FieldSets matching
    # `cls.field_sets`.
    field_sets_consume_only: ClassVar[tuple[type[FieldSet], ...]] = ()

    # True if this request type is only valid at the root of a compile graph.
    root_only: ClassVar[bool] = False

    @staticmethod
    def for_targets(
        union_membership: UnionMembership,
        component: CoarsenedTarget,
        resolve: CoursierResolveKey,
        *,
        root: bool = False,
    ) -> ClasspathEntryRequest:
        """Constructs a subclass compatible with the members of the CoarsenedTarget.

        If the CoarsenedTarget is a root of a compile graph, pass `root=True` to allow usage of
        request types which are marked `root_only`.
        """

        compatible = []
        partial = []
        consume_only = []
        impls = union_membership.get(ClasspathEntryRequest)
        for impl in impls:
            classification = ClasspathEntryRequest.classify_impl(impl, component)
            if classification == _ClasspathEntryRequestClassification.INCOMPATIBLE:
                continue
            elif classification == _ClasspathEntryRequestClassification.COMPATIBLE:
                compatible.append(impl)
            elif classification == _ClasspathEntryRequestClassification.PARTIAL:
                partial.append(impl)
            elif classification == _ClasspathEntryRequestClassification.CONSUME_ONLY:
                consume_only.append(impl)

        if len(compatible) == 1:
            if not root and impl.root_only:
                raise ClasspathRootOnlyWasInner(
                    "The following targets had dependees, but can only be used as roots in a "
                    f"build graph:\n{component.bullet_list()}"
                )
            return compatible[0](component, resolve, None)

        # No single request can handle the entire component: see whether there are exactly one
        # partial and consume_only impl to handle it together.
        if not compatible and len(partial) == 1 and len(consume_only) == 1:
            # TODO: Precompute which requests might be partial for others?
            if set(partial[0].field_sets).issubset(set(consume_only[0].field_sets_consume_only)):
                return partial[0](component, resolve, consume_only[0](component, resolve, None))

        impls_str = ", ".join(sorted(impl.__name__ for impl in impls))
        if compatible:
            raise ClasspathSourceAmbiguity(
                f"More than one JVM classpath provider ({impls_str}) was compatible with "
                f"the inputs:\n{component.bullet_list()}"
            )
        else:
            # TODO: There is more subtlety of error messages possible here if there are multiple
            # partial providers, but can cross that bridge when we have them (multiple Scala or Java
            # compiler implementations, for example).
            raise ClasspathSourceMissing(
                f"No JVM classpath providers (from: {impls_str}) were compatible with the "
                f"combination of inputs:\n{component.bullet_list()}"
            )

    @staticmethod
    def classify_impl(
        impl: type[ClasspathEntryRequest], component: CoarsenedTarget
    ) -> _ClasspathEntryRequestClassification:
        targets = component.members
        compatible = sum(1 for t in targets for fs in impl.field_sets if fs.is_applicable(t))
        if compatible == 0:
            return _ClasspathEntryRequestClassification.INCOMPATIBLE
        if compatible == len(targets):
            return _ClasspathEntryRequestClassification.COMPATIBLE
        consume_only = sum(
            1 for t in targets for fs in impl.field_sets_consume_only if fs.is_applicable(t)
        )
        if compatible + consume_only == len(targets):
            return _ClasspathEntryRequestClassification.CONSUME_ONLY
        return _ClasspathEntryRequestClassification.PARTIAL


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
    def args(cls, entries: Iterable[ClasspathEntry], *, prefix: str = "") -> Iterator[str]:
        """Returns the filenames for the given entries.

        TODO: See whether this method can be completely eliminated in favor of
        `immutable_inputs(_args)`.

        To compute transitive filenames, first expand the entries with `cls.closure()`.
        """
        return (os.path.join(prefix, f) for cpe in entries for f in cpe.filenames)

    @classmethod
    def immutable_inputs(
        cls, entries: Iterable[ClasspathEntry], *, prefix: str = ""
    ) -> Iterator[tuple[str, Digest]]:
        """Returns (relpath, Digest) tuples for use with `Process.immutable_input_digests`.

        To compute transitive input tuples, first expand the entries with `cls.closure()`.
        """
        return ((os.path.join(prefix, cpe.digest.fingerprint[:12]), cpe.digest) for cpe in entries)

    @classmethod
    def immutable_inputs_args(
        cls, entries: Iterable[ClasspathEntry], *, prefix: str = ""
    ) -> Iterator[str]:
        """Returns the relative filenames for the given entries to be used as immutable_inputs.

        To compute transitive input tuples, first expand the entries with `cls.closure()`.
        """
        for cpe in entries:
            fingerprint_prefix = cpe.digest.fingerprint[:12]
            for filename in cpe.filenames:
                yield os.path.join(prefix, fingerprint_prefix, filename)

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
        #   see https://github.com/pantsbuild/pants/issues/13942.
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
