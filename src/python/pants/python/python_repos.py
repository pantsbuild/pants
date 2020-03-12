# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, cast

from pants.option.optionable import option
from pants.subsystem.subsystem import Subsystem


class PythonRepos(Subsystem):
    """A python code repository.

    Note that this is part of the Pants core, and not the python backend, because it's used to
    bootstrap Pants plugins.
    """

    options_scope = "python-repos"

    @property                   # type: ignore[misc]
    @option(
        "--repos", advanced=True, default=[], fingerprint=True, help="URLs of code repositories.",
    )
    def repos(self) -> List[str]:
        return cast(List[str], self.get_options().repos)

    @property                   # type: ignore[misc]
    @option(
        "--indexes",
        advanced=True,
        fingerprint=True,
        default=["https://pypi.org/simple/"],
        help="URLs of code repository indexes.",
    )
    def indexes(self) -> List[str]:
        return cast(List[str], self.get_options().indexes)
