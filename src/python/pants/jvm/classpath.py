# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass

from pants.core.util_rules import system_binaries
from pants.core.util_rules.system_binaries import UnzipBinary
from pants.engine.fs import Digest, MergeDigests, RemovePrefix
from pants.engine.intrinsics import merge_digests, remove_prefix
from pants.engine.process import Process, execute_process_or_raise
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import CoarsenedTargets
from pants.jvm.compile import (
    ClasspathEntry,
    ClasspathEntryRequest,
    ClasspathEntryRequestFactory,
    get_fallible_classpath_entry,
    required_classfiles,
)
from pants.jvm.compile import rules as jvm_compile_rules
from pants.jvm.resolve.coursier_fetch import select_coursier_resolve_for_targets
from pants.jvm.resolve.key import CoursierResolveKey
from pants.util.logging import LogLevel

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
    resolve = await select_coursier_resolve_for_targets(coarsened_targets, **implicitly())

    # Then request classpath entries for each root.
    fallible_classpath_entries = await concurrently(
        get_fallible_classpath_entry(
            **implicitly(
                {
                    classpath_entry_request.for_targets(
                        component=t, resolve=resolve, root=True
                    ): ClasspathEntryRequest
                }
            )
        )
        for t in coarsened_targets
    )
    classpath_entries = await concurrently(
        required_classfiles(fce) for fce in fallible_classpath_entries
    )

    return Classpath(classpath_entries, resolve)


@dataclass(frozen=True)
class LooseClassfiles:
    """The contents of a classpath entry as loose classfiles.

    Note that `ClasspathEntry` and `Classpath` both guarantee that they contain JAR files, and so
    creating loose classfiles from them involves extracting their entry.
    """

    digest: Digest


@rule
async def loose_classfiles(
    classpath_entry: ClasspathEntry, unzip_binary: UnzipBinary
) -> LooseClassfiles:
    dest_dir = "dest"
    process_results = await concurrently(
        execute_process_or_raise(
            **implicitly(
                Process(
                    argv=[
                        unzip_binary.path,
                        "-d",
                        dest_dir,
                        filename,
                    ],
                    output_directories=(dest_dir,),
                    description=f"Extract {filename}",
                    immutable_input_digests=dict(
                        ClasspathEntry.immutable_inputs([classpath_entry])
                    ),
                    level=LogLevel.TRACE,
                )
            )
        )
        for filename in ClasspathEntry.immutable_inputs_args([classpath_entry])
    )

    merged_digest = await merge_digests(MergeDigests(pr.output_digest for pr in process_results))

    return LooseClassfiles(await remove_prefix(RemovePrefix(merged_digest, dest_dir)))


def rules():
    return [
        *collect_rules(),
        *system_binaries.rules(),
        *jvm_compile_rules(),
    ]
