# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.engine.target import COMMON_TARGET_FIELDS, Sources, StringSequenceField, Target


class MavenRequirementsField(StringSequenceField):
    alias = "maven_requirements"
    help = (
        "A sequence of Maven coordinate strings, e.g. ['org.scala-lang:scala-compiler:2.12.0', "
        "'org.scala-lang:scala-library:2.12.0']."
    )


class JvmLockfileSources(Sources):
    expected_file_extensions = (".lockfile",)
    expected_num_files = range(
        2
    )  # NOTE: This actually means 0 or 1 files; `range`'s end is noninclusive.
    help = (
        "A single Pants Coursier Lockfile source.\n\n"
        "Use `./pants coursier-resolve ...` to generate (or regenerate) the Lockfile."
        " If the Lockfile doesn't exist on disk, the first run of `coursier-resolve` will attempt"
        " to generate it for you to the default file name ('coursier_resolve.lockfile')."
        " After running `coursier-resolve` for the first time, you should update this field's"
        "`sources` to explicit take ownership of the generated lockfile."
    )


class JvmDependencyLockfile(Target):
    alias = "coursier_lockfile"
    core_fields = (*COMMON_TARGET_FIELDS, JvmLockfileSources, MavenRequirementsField)
    help = "A Coursier lockfile along with the Maven-style requirements used to regenerate the lockfile."
