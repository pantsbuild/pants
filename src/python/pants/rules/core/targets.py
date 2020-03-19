# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import ClassVar

from pants.engine.target import COMMON_TARGET_FIELDS, Sources, Target


class FilesSources(Sources):
    """Sources for loose files.

    These will not have their source roots stripped, unlike every other Sources subclass.
    """


class Files(Target):
    """A collection of loose files."""

    core_fields: ClassVar = (*COMMON_TARGET_FIELDS, FilesSources)
