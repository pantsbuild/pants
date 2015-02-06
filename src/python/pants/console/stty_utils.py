# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import subprocess
from contextlib import contextmanager


@contextmanager
def preserve_stty_settings():
  """Run potentially stty-modifying operations, e.g., REPL execution, in this contextmanager."""
  stty_settings = STTYSettings()
  stty_settings.save_stty_options()
  yield
  stty_settings.restore_ssty_options()


class STTYSettings(object):
  """Saves/restores stty settings, e.g., during REPL execution."""

  def __init__(self):
    self._stty_options = None

  def save_stty_options(self):
    self._stty_options = self._run_cmd('stty -g 2>/dev/null')

  def restore_ssty_options(self):
    self._run_cmd('stty ' + self._stty_options)

  def _run_cmd(self, cmd):
    po = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
    stdout, _ = po.communicate()
    return stdout
