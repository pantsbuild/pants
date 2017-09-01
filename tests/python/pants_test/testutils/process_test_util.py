# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import psutil


def check_process_exists_by_command(name):
  result = False
  for proc in psutil.process_iter():
    try:
      result |= name in ''.join(proc.cmdline())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
      pass
  return result
