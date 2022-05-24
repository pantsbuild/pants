# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from pathlib import PurePath
from typing import Sequence

from pants.core.goals.package import OutputPathField
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    InvalidFieldException,
    MultipleSourcesField,
    Target,
    generate_multiple_sources_field_help_message,
)
from pants.util.strutil import softwrap


class SphinxProjectSourcesField(MultipleSourcesField):
    # TODO: support markdown
    default = ("conf.py", "**/*.rst")
    expected_file_extensions = (".py", ".rst")
    uses_source_roots = False
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['conf.py', 'new_*.rst', '!old_ignore.rst']`"
    )

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
        expected_conf_py = os.path.join(self.address.spec_path, "conf.py")
        if py_files[0] != expected_conf_py:
            # TODO: mention how docs from first-party code work once implemented (dependencies).
            raise InvalidFieldException(
                softwrap(
                    f"""
                    The {repr(self.alias)} field in target {self.address} must have exactly one
                    `.py` file named `conf.py`, with the full path {expected_conf_py}, but it had
                    the Python file `{py_files[0]}` instead.

                    Make sure you're declaring the target in the same directory as the `conf.py`
                    file.
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
