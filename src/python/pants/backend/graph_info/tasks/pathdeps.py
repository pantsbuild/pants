# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_environment import get_buildroot
from pants.base.deprecated import deprecated_conditional
from pants.task.console_task import ConsoleTask


class PathDeps(ConsoleTask):
  """List all paths containing BUILD files the target depends on."""

  def console_output(self, targets):
    deprecated_conditional(lambda: True, '1.5.0.dev0',
                           'The `pathdeps` goal is deprecated. Please use `filedeps` instead.')
    def is_safe(t):
      return hasattr(t, 'address') and hasattr(t.address, 'rel_path')
    buildroot = get_buildroot()
    return set(os.path.normpath(os.path.join(buildroot, os.path.dirname(t.address.rel_path)))
               for t in targets if is_safe(t))
