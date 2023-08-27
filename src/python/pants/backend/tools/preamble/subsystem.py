# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from typing import Sequence

from pants.option.option_types import DictOption, SkipOption
from pants.option.subsystem import Subsystem
from pants.source.filespec import FilespecMatcher
from pants.util.strutil import help_text, softwrap


class PreambleSubsystem(Subsystem):
    options_scope = "preamble"
    name = "preamble"
    help = help_text(
        """
        Formats files with a preamble, with the preamble looked up based on path.

        This is useful for things such as copyright headers or shebang lines.

        Pants substitutes the following identifiers (following Python's `string.Template` substitutions):
        - $year: The current year (only used when actually writing the year to the file).
        """
    )

    skip = SkipOption("fmt")

    _template_by_globs = DictOption[str](
        help=softwrap(
            """
            Which preamble template to use based on the path globs (relative to the build root).

            Example:

                {
                    '*.rs': '// Copyright (c) $year\\n// Line 2\\n'
                    '*.py:!__init__.py': '# Copyright (c) $year\\n# Line 2\\n',
                }

            It might be helpful to load this config from a JSON or YAML file. To do that, set
            `[preamble].config = '@path/to/config.yaml'`, for example.
            """
        ),
        fromfile=True,
    )

    @property
    def template_by_globs(self) -> dict[tuple[str, ...], str]:
        return {tuple(key.split(":")): value for key, value in self._template_by_globs.items()}

    def get_template_by_path(self, filepaths: Sequence[str]) -> dict[str, str]:
        """Returns a mapping from path to (most-relevant) template."""
        filepaths_to_test = set(filepaths)
        template_by_path = {}
        for globs, template in self.template_by_globs.items():
            if not filepaths_to_test:
                break

            matched_filepaths = FilespecMatcher(
                includes=[
                    (glob[2:] if glob.startswith(r"\\!") else glob)
                    for glob in globs
                    if not glob.startswith("!")
                ],
                excludes=[glob[1:] for glob in globs if glob.startswith("!")],
            ).matches(tuple(filepaths_to_test))
            filepaths_to_test -= set(matched_filepaths)
            for filepath in matched_filepaths:
                template_by_path[filepath] = template

        return template_by_path
