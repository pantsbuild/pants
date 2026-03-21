# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.ng.subsystem import UniversalSubsystem, option


# TODO: We want this to work with environments, which we probably want to achieve via
#  a config context (e.g., 'remote' in the config file name) instead of the og
#  "environment-aware" concept.
class System(UniversalSubsystem):
    options_scope = "system"
    help = "Settings related to the system Pants runs on"

    @option(help="Path to sh", default="/bin/sh")
    def sh_path(self) -> str: ...
