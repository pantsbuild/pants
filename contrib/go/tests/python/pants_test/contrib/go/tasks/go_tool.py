# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import subprocess


class GoTool(object):

  _go_installed = None

  @staticmethod
  def go_installed():
    if GoTool._go_installed is None:
      retcode = subprocess.call(['which', 'go'])
      GoTool._go_installed = (retcode == 0)
    return GoTool._go_installed
