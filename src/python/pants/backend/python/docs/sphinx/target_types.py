# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import PurePath
from typing import Sequence

from pants.core.goals.package import OutputPathField
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    InvalidFieldException,
    MultipleSourcesField,
    Target,
)
from pants.util.strutil import softwrap


class SphinxProjectSourcesField(MultipleSourcesField):
    # TODO: support markdown
    default = ("conf.py", "**/*.rst")
    expected_file_extensions = (".py", ".rst")

    def validate_resolved_files(self, files: Sequence[str]) -> None:
        super().validate_resolved_files(files)
        py_files = [f for f in files if PurePath(f).suffix == ".py"]
        if not py_files:
            raise InvalidFieldException(
                softwrap(
                    f"""
                    The {repr(self.alias)} field in target {self.address} must have exactly one
                    `.py` file named `conf.py`, but no `.py` files found.
                    """
                )
            )
        if len(py_files) > 1:
            raise InvalidFieldException(
                softwrap(
                    f"""
                    The {repr(self.alias)} field in target {self.address} must have exactly one
                    `.py` file named `conf.py`, but it had multiple `.py` files: {sorted(py_files)}
                    """
                )
            )
        # TODO: check if it's conf.py in the root of the dir
        if py_files[0] == "TODO":
            raise InvalidFieldException(
                softwrap(
                    """
                    
                    """
                )
            )


class SphinxProjectTarget(Target):
    alias = "sphinx_project"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        SphinxProjectSourcesField,
        OutputPathField,
        # TODO: Add `dependencies` when that makes sense. Likely we just want deps on Python targets.
    )
    help = "A website generated via Sphinx."
