# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, cast

from pants.option.subsystem import Subsystem


class PythonRepos(Subsystem):
    options_scope = "python-repos"
    help = (
        "External Python code repositories, such as PyPI.\n\nThese options may be used to point to "
        "custom cheeseshops when resolving requirements."
    )

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--repos",
            advanced=True,
            type=list,
            default=[],
            help=(
                "URLs of code repositories to look for requirements. In Pip and Pex, this option "
                "corresponds to the `--find-links` option."
            ),
        )
        register(
            "--indexes",
            advanced=True,
            type=list,
            default=["https://pypi.org/simple/"],
            help=(
                "URLs of code repository indexes to look for requirements. If set to an empty "
                "list, then Pex will use no indices (meaning it will not use PyPI). The values "
                "should be compliant with PEP 503."
            ),
        )

    @property
    def repos(self) -> List[str]:
        return cast(List[str], self.options.repos)

    @property
    def indexes(self) -> List[str]:
        return cast(List[str], self.options.indexes)
