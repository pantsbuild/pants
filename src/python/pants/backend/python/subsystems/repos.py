# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterator

from pants.option.option_types import StrListOption
from pants.option.subsystem import Subsystem


class PythonRepos(Subsystem):
    options_scope = "python-repos"
    help = (
        "External Python code repositories, such as PyPI.\n\nThese options may be used to point to "
        "custom cheeseshops when resolving requirements."
    )

    pypi_index = "https://pypi.org/simple/"

    repos = StrListOption(
        "--repos",
        help=(
            "URLs of code repositories to look for requirements. In Pip and Pex, this option "
            "corresponds to the `--find-links` option."
        ),
        advanced=True,
    )
    indexes = StrListOption(
        "--indexes",
        default=[pypi_index],
        help=(
            "URLs of code repository indexes to look for requirements. If set to an empty "
            "list, then Pex will use no indices (meaning it will not use PyPI). The values "
            "should be compliant with PEP 503."
        ),
        advanced=True,
    )

    @property
    def pex_args(self) -> Iterator[str]:
        # NB: In setting `--no-pypi`, we rely on the default value of `--python-repos-indexes`
        # including PyPI, which will override `--no-pypi` and result in using PyPI in the default
        # case. Why set `--no-pypi`, then? We need to do this so that
        # `--python-repos-repos=['custom_url']` will only point to that index and not include PyPI.
        yield "--no-pypi"
        yield from (f"--index={index}" for index in self.indexes)
        yield from (f"--repo={repo}" for repo in self.repos)
