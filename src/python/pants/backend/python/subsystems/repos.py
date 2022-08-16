# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.option.option_types import StrListOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


class PythonRepos(Subsystem):
    options_scope = "python-repos"
    help = softwrap(
        """
        External Python code repositories, such as PyPI.

        These options may be used to point to custom cheeseshops when resolving requirements.
        """
    )

    pypi_index = "https://pypi.org/simple/"

    repos = StrListOption(
        help=softwrap(
            """
            URLs of code repositories to look for requirements. In Pip and Pex, this option
            corresponds to the `--find-links` option.
            """
        ),
        removal_version="2.16.0.dev0",
        removal_hint=softwrap(
            """
            Use `[python].resolves_to_find_links`, which allows you to set --find-links on a
            per-resolve basis for more flexibility. That is, you can configure differently how
            individual Python tools like Pytest and resolves from `[python].resolves` are installed.

            To keep this option's behavior, set `[python].resolves_to_find_links` with the key
            `__default__` and the value you used on this option.
            """
        ),
        advanced=True,
    )
    indexes = StrListOption(
        default=[pypi_index],
        help=softwrap(
            """
            URLs of code repository indexes to look for requirements. If set to an empty
            list, then Pex will use no indices (meaning it will not use PyPI). The values
            should be compliant with PEP 503.
            """
        ),
        removal_version="2.16.0.dev0",
        removal_hint=softwrap(
            """
            Use `[python].resolves_to_indexes`, which allows you to set indexes on a
            per-resolve basis for more flexibility. That is, you can configure differently how
            individual Python tools like Pytest and resolves from `[python].resolves` are installed.

            To keep this option's behavior, set `[python].resolves_to_indexes` with the key
            `__default__` and the value you used on this option.
            """
        ),
        advanced=True,
    )
