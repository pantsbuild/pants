# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.target import COMMON_TARGET_FIELDS, Dependencies, Sources, Target

# -----------------------------------------------------------------------------------------------
# `files` target
# -----------------------------------------------------------------------------------------------


class FilesSources(Sources):
    required = True


class Files(Target):
    """A collection of loose files which do not have their source roots stripped.

    The sources of a `files` target can be accessed via language-specific APIs, such as Python's
    `open()`. Unlike the similar `resources()` target type, Pants will not strip the source root of
    `files()`, meaning that `src/python/project/f1.txt` will not be stripped down to
    `project/f1.txt`.
    """

    alias = "files"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, FilesSources)


# -----------------------------------------------------------------------------------------------
# `resources` target
# -----------------------------------------------------------------------------------------------


class ResourcesSources(Sources):
    required = True


class Resources(Target):
    """A collection of loose files.

    The sources of a `resources` target can be accessed via language-specific APIs, such as Python's
    `open()`. Resources are meant to be included in deployable units like JARs or Python wheels.
    Unlike the similar `files()` target type, Pants will strip the source root of `resources()`,
    meaning that `src/python/project/f1.txt` will be stripped down to `project/f1.txt`.
    """

    alias = "resources"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, ResourcesSources)


# -----------------------------------------------------------------------------------------------
# `target` generic target
# -----------------------------------------------------------------------------------------------


class GenericTarget(Target):
    """A generic target with no specific target type.

    This is useful for aggregate targets: https://www.pantsbuild.org/target_aggregate.html.
    """

    alias = "target"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, Sources)
