# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import subprocess

from pants.util.osutil import get_os_name


class OpenError(Exception):
  """Indicates an error opening a file in a desktop application."""


def _mac_open(files):
  subprocess.call(['open'] + list(files))


def _linux_open(files):
  cmd = "xdg-open"
  if not _cmd_exists(cmd):
    raise OpenError("The program '{}' isn't in your PATH. Please install and re-run this "
                    "goal.".format(cmd))
  for f in list(files):
    subprocess.call([cmd, f])


# From: http://stackoverflow.com/questions/377017/test-if-executable-exists-in-python
def _cmd_exists(cmd):
  return subprocess.call(["/usr/bin/which", cmd], shell=False, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE) == 0


_OPENER_BY_OS = {
  'darwin': _mac_open,
  'linux': _linux_open
}


def ui_open(*files):
  """Attempts to open the given files using the preferred desktop viewer or editor.

  :raises :class:`OpenError`: if there is a problem opening any of the files.
  """
  if files:
    osname = get_os_name()
    opener = _OPENER_BY_OS.get(osname)
    if opener:
      opener(files)
    else:
      raise OpenError('Open currently not supported for ' + osname)
