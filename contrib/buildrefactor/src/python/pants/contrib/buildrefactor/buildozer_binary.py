# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import subprocess

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.binaries.binary_tool import NativeTool


logger = logging.getLogger(__name__)


class BuildozerBinary(NativeTool):
    # Note: Not in scope 'buildozer' because that's the name of the singleton task
    # that runs buildozer.
    options_scope = "buildozer-binary"
    name = "buildozer"
    default_version = "0.6.0-80c7f0d45d7e40fa1f7362852697d4a03df557b3"

    replaces_scope = "buildozer"
    replaces_name = "version"

    def execute(self, buildozer_command, spec, context=None):
        try:
            subprocess.check_call(
                [self.select(context), buildozer_command, spec], cwd=get_buildroot()
            )
        except subprocess.CalledProcessError as err:
            if err.returncode == 3:
                logger.warning("{} ... no changes were made".format(buildozer_command))
            else:
                raise TaskError(
                    "{} ... exited non-zero ({}).".format(buildozer_command, err.returncode)
                )
