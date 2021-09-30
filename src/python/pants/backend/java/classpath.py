# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Iterator

from pants.backend.java.compile.javac import CompiledClassfiles, CompileJavaSourceRequest
from pants.engine.addresses import Addresses
from pants.engine.fs import AddPrefix, Digest, MergeDigests, Snapshot
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    CoarsenedTargets,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.jvm.resolve.coursier_fetch import (
    CoursierLockfileForTargetRequest,
    CoursierResolvedLockfile,
    MaterializedClasspath,
    MaterializedClasspathRequest,
)

_USERCP_RELPATH = "__usercp"


@dataclass(frozen=True)
class Classpath:
    """A transitive classpath which is sufficient to launch the target(s) it was generated for.

    This classpath is guaranteed to contain only JAR files.
    """

    content: Snapshot

    def classpath_args(self, prefix: str | None = None) -> Iterator[str]:
        """Construct the argument to be passed to `java -cp`.

        :param prefix: if set, will be prepended to all entries.  This is useful
            if the process working directory is not the same as the root
            directory for the process input `Digest`.
        """
        return self._classpath(lambda _: True, prefix=prefix)

    def user_classpath_args(self, prefix: str | None = None) -> Iterator[str]:
        """Like `classpath_arg`, but returns only entries corresponding to first-party code."""
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
async def classpath(addresses: Addresses) -> Classpath:
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(addresses))
    coarsened_targets = await Get(
        CoarsenedTargets, Addresses(t.address for t in transitive_targets.closure)
    )

    lockfile = await Get(
        CoursierResolvedLockfile,
        CoursierLockfileForTargetRequest(Targets(transitive_targets.closure)),
    )
    materialized_classpath = await Get(
        MaterializedClasspath,
        MaterializedClasspathRequest(
            prefix="__thirdpartycp",
            lockfiles=(lockfile,),
        ),
    )
    transitive_user_classfiles = await MultiGet(
        Get(CompiledClassfiles, CompileJavaSourceRequest(component=t)) for t in coarsened_targets
    )
    merged_transitive_user_classfiles_digest = await Get(
        Digest, MergeDigests(classfiles.digest for classfiles in transitive_user_classfiles)
    )
    prefixed_transitive_user_classfiles_digest = await Get(
        Digest, AddPrefix(merged_transitive_user_classfiles_digest, _USERCP_RELPATH)
    )

    return Classpath(
        await Get(
            Snapshot,
            MergeDigests(
                (
                    prefixed_transitive_user_classfiles_digest,
                    materialized_classpath.digest,
                )
            ),
        )
    )


def rules():
    return collect_rules()
