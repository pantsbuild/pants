# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.option.option_types import StrListOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


class PoetrySubsystem(Subsystem):
    options_scope = "poetry"
    help = "Deprecated. No longer does anything"

    _removal_hint = softwrap(
        """
        The `[poetry]` subsystem is deprecated and no longer does anything because
        `[python].lockfile_generator = 'pex'` was removed.
        """
    )

    version = StrOption(
        default=None,
        advanced=True,
        help=help,
        removal_version="2.16.0.dev0",
        removal_hint=_removal_hint,
    )
    extra_requirements = StrListOption(
        advanced=True, help=help, removal_version="2.16.0.dev0", removal_hint=_removal_hint
    )
    interpreter_constraints = StrListOption(
        advanced=True, help=help, removal_version="2.16.0.dev0", removal_hint=_removal_hint
    )
    lockfile = StrOption(
        default=None,
        advanced=True,
        help=help,
        removal_version="2.16.0.dev0",
        removal_hint=_removal_hint,
    )
