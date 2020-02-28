# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.subsystem.subsystem import Subsystem


class PythonRepos(Subsystem):
    """A python code repository.

    Note that this is part of the Pants core, and not the python backend, because it's used to
    bootstrap Pants plugins.
    """

    options_scope = "python-repos"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--repos",
            advanced=True,
            type=list,
            default=[],
            fingerprint=True,
            help="URLs of code repositories.",
        )
        register(
            "--indexes",
            advanced=True,
            type=list,
            fingerprint=True,
            default=["https://pypi.org/simple/"],
            help="URLs of code repository indexes.",
        )

    @property
    def repos(self):
        return self.get_options().repos

    @property
    def indexes(self):
        return self.get_options().indexes
