# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import help_text


class BUILDDeprecationsFixer(Subsystem):
    options_scope = "build-deprecations-fixer"
    name = "BUILD Deprecations Fixer"
    help = help_text(
        """
        A tool/plugin for fixing BUILD file deprecations (where possible).

        This includes deprecations for:

          - Renamed targets
          - Renamed fields
        """
    )

    skip = SkipOption("fix")
