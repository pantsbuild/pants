# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterator

from pants.engine.fs import Digest
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import CoarsenedTargets
from pants.jvm.compile import ClasspathEntry, ClasspathEntryRequest, ClasspathEntryRequestFactory
from pants.jvm.resolve.key import CoursierResolveKey

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Classpath:
    """A transitive classpath which is sufficient to launch the target(s) it was generated for.

    There are two primary ways to consume a Classpath:
        1. Using the `(root_)immutable_inputs` methods, which produce the argument to
           `Process.immutable_input_digests` and adapted CLI args for use with that argument.
        2. Using the `digests` and `(root_)args` methods, which can be merged to produce the
           argument to `Process.input_digest` and CLI args for use with a digest.
    The first approach should be preferred, because it allows for symlinking of inputs. If
    possible, the latter method should be removed when consumers have migrated.

    This classpath is guaranteed to contain only JAR files.
    """

    entries: tuple[ClasspathEntry, ...]
    resolve: CoursierResolveKey

    def args(self, *, prefix: str = "") -> Iterator[str]:
        """All transitive filenames for this Classpath."""
        return ClasspathEntry.args(ClasspathEntry.closure(self.entries), prefix=prefix)

    def root_args(self, *, prefix: str = "") -> Iterator[str]:
        """The root filenames for this Classpath."""
        return ClasspathEntry.args(self.entries, prefix=prefix)

    def digests(self) -> Iterator[Digest]:
        """All transitive Digests for this Classpath."""
        return (entry.digest for entry in ClasspathEntry.closure(self.entries))

    def immutable_inputs(self, *, prefix: str = "") -> Iterator[tuple[str, Digest]]:
        """Returns (relpath, Digest) tuples for use with `Process.immutable_input_digests`."""
        return ClasspathEntry.immutable_inputs(ClasspathEntry.closure(self.entries), prefix=prefix)

    def immutable_inputs_args(self, *, prefix: str = "") -> Iterator[str]:
        """Returns relative filenames for the given entries to be used as immutable_inputs."""
        return ClasspathEntry.immutable_inputs_args(
            ClasspathEntry.closure(self.entries), prefix=prefix
        )

    def root_immutable_inputs(self, *, prefix: str = "") -> Iterator[tuple[str, Digest]]:
        """Returns root (relpath, Digest) tuples for use with `Process.immutable_input_digests`."""
        return ClasspathEntry.immutable_inputs(self.entries, prefix=prefix)

    def root_immutable_inputs_args(self, *, prefix: str = "") -> Iterator[str]:
        """Returns root relative filenames for the given entries to be used as immutable_inputs."""
        return ClasspathEntry.immutable_inputs_args(self.entries, prefix=prefix)


@rule
async def classpath(
    coarsened_targets: CoarsenedTargets,
    classpath_entry_request: ClasspathEntryRequestFactory,
) -> Classpath:
    # Compute a single shared resolve for all of the roots, which will validate that they
    # are compatible with one another.
    resolve = await Get(CoursierResolveKey, CoarsenedTargets, coarsened_targets)

    # Then request classpath entries for each root.
    classpath_entries = await MultiGet(
        Get(
            ClasspathEntry,
            ClasspathEntryRequest,
            classpath_entry_request.for_targets(component=t, resolve=resolve, root=True),
        )
        for t in coarsened_targets
    )

    return Classpath(classpath_entries, resolve)


def rules():
    return collect_rules()
