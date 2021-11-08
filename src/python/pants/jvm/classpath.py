# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Iterator

from pants.engine.fs import AddPrefix, Digest, MergeDigests, Snapshot
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import CoarsenedTargets, Targets
from pants.engine.unions import UnionMembership
from pants.jvm.compile import ClasspathEntry, ClasspathEntryRequest
from pants.jvm.resolve.key import CoursierResolveKey

_USERCP_RELPATH = "__cp"


@dataclass(frozen=True)
class Classpath:
    """A transitive classpath which is sufficient to launch the target(s) it was generated for.

    This classpath is guaranteed to contain only JAR files.

    TODO: Reuse `ClasspathEntry` prefixes, and replace `user_classpath` logic with inspecting only
    the "root" `ClasspathEntry` for a test target.
    """

    content: Snapshot

    def classpath_entries(self, prefix: str | None = None) -> Iterator[str]:
        """Returns optionally prefixed classpath entry filenames.

        :param prefix: if set, will be prepended to all entries.  This is useful
            if the process working directory is not the same as the root
            directory for the process input `Digest`.
        """
        return self._classpath(lambda _: True, prefix=prefix)

    def user_classpath_entries(self, prefix: str | None = None) -> Iterator[str]:
        """Like `classpath_entries`, but returns only entries corresponding to first-party code."""
        return self._classpath(lambda f: f.startswith(_USERCP_RELPATH), prefix=prefix)

    def _classpath(
        self, predicate: Callable[[str], bool], prefix: str | None = None
    ) -> Iterator[str]:
        def maybe_add_prefix(file_name: str) -> str:
            if prefix is None:
                return file_name
            return os.path.join(prefix, file_name)

        return (
            maybe_add_prefix(file_path) for file_path in self.content.files if predicate(file_path)
        )


@rule
async def classpath(
    coarsened_targets: CoarsenedTargets,
    union_membership: UnionMembership,
) -> Classpath:
    targets = Targets(t for ct in coarsened_targets.closure() for t in ct.members)

    resolve = await Get(CoursierResolveKey, Targets, targets)

    transitive_classpath_entries = await MultiGet(
        Get(
            ClasspathEntry,
            ClasspathEntryRequest,
            ClasspathEntryRequest.for_targets(union_membership, component=t, resolve=resolve),
        )
        for t in coarsened_targets.closure()
    )
    merged_transitive_classpath_entries_digest = await Get(
        Digest, MergeDigests(classfiles.digest for classfiles in transitive_classpath_entries)
    )

    return Classpath(
        await Get(Snapshot, AddPrefix(merged_transitive_classpath_entries_digest, _USERCP_RELPATH))
    )


def rules():
    return collect_rules()
