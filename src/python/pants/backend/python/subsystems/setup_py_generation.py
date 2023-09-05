# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import enum

from pants.option.option_types import BoolOption, EnumOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


@enum.unique
class FirstPartyDependencyVersionScheme(enum.Enum):
    EXACT = "exact"  # i.e., ==
    COMPATIBLE = "compatible"  # i.e., ~=
    ANY = "any"  # i.e., no specifier


class SetupPyGeneration(Subsystem):
    options_scope = "setup-py-generation"
    help = "Options to control how setup.py is generated from a `python_distribution` target."

    # Generating setup is the more aggressive thing to do, so we'd prefer that the default
    # be False. However that would break widespread existing usage, so we'll make that
    # change in a future deprecation cycle.
    generate_setup_default = BoolOption(
        default=True,
        help=softwrap(
            """
            The default value for the `generate_setup` field on `python_distribution` targets.
            Can be overridden per-target by setting that field explicitly. Set this to False
            if you mostly rely on handwritten setup files (`setup.py`, `setup.cfg` and similar).
            Leave as True if you mostly rely on Pants generating setup files for you.
            """
        ),
    )

    first_party_dependency_version_scheme = EnumOption(
        default=FirstPartyDependencyVersionScheme.EXACT,
        help=softwrap(
            """
            What version to set in `install_requires` when a `python_distribution` depends on
            other `python_distribution`s. If `exact`, will use `==`. If `compatible`, will
            use `~=`. If `any`, will leave off the version. See
            https://www.python.org/dev/peps/pep-0440/#version-specifiers.
            """
        ),
    )

    def first_party_dependency_version(self, version: str) -> str:
        """Return the version string (e.g. '~=4.0') for a first-party dependency.

        If the user specified to use "any" version, then this will return an empty string.
        """
        scheme = self.first_party_dependency_version_scheme
        if scheme == FirstPartyDependencyVersionScheme.ANY:
            return ""
        specifier = "==" if scheme == FirstPartyDependencyVersionScheme.EXACT else "~="
        return f"{specifier}{version}"
