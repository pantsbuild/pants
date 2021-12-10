# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from typing import Iterator

from pants.engine.collection import Collection
from pants.engine.fs import Digest
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import CoarsenedTargets, Targets
from pants.engine.unions import UnionMembership
from pants.jvm.compile import ClasspathEntry, ClasspathEntryRequest
from pants.jvm.resolve.key import CoursierResolveKey

logger = logging.getLogger(__name__)


class Classpath(Collection[ClasspathEntry]):
    """A transitive classpath which is sufficient to launch the target(s) it was generated for.

    This classpath is guaranteed to contain only JAR files.
    """

    def args(self, *, prefix: str = "") -> Iterator[str]:
        """All transitive filenames for this Classpath."""
        return ClasspathEntry.args(ClasspathEntry.closure(self), prefix=prefix)

    def root_args(self, *, prefix: str = "") -> Iterator[str]:
        """The root filenames for this Classpath."""
        return ClasspathEntry.args(self, prefix=prefix)

    def digests(self) -> Iterator[Digest]:
        """All transitive Digests for this Classpath."""
        return (entry.digest for entry in ClasspathEntry.closure(self))


@rule
async def classpath(
    coarsened_targets: CoarsenedTargets,
    union_membership: UnionMembership,
) -> Classpath:
    resolve = await Get(
        CoursierResolveKey,
        Targets,
        Targets(t for ct in coarsened_targets.closure() for t in ct.members),
    )

    classpath_entries = await MultiGet(
        Get(
            ClasspathEntry,
            ClasspathEntryRequest,
            ClasspathEntryRequest.for_targets(union_membership, component=t, resolve=resolve),
        )
        for t in coarsened_targets
    )

    return Classpath(classpath_entries)


def rules():
    return collect_rules()
