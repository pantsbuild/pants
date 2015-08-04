# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.pantsd.service.pants_service import PantsService


class BuildGraphService(PantsService):
  def run(self):
    """Main service entrypoint. Called via Thread.start() via PantsDaemon.run()."""
    self._intentional_sleep()
