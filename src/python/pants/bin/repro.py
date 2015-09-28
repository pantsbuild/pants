# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import sys

from pants.base.build_environment import get_buildroot
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import open_tar, temporary_file
from pants.util.dirutil import chmod_plus_x


logger = logging.getLogger(__name__)


class ReproError(Exception):
  pass


class Reproducer(Subsystem):
  options_scope = 'repro'

  @classmethod
  def register_options(cls, register):
    register('--capture', metavar='<repro_path>', default=None,
             help='Capture information about this pants run (including the entire workspace) '
                  'into a tar.gz file that can be used to help debug build problems.')

  def create_repro(self):
    """Return a Repro instance for capturing a repro of the current workspace state.

    :return: a Repro instance, or None if no repro was requested.
    :rtype: `pants.bin.repro.Repro`
    """
    path = self.get_options().capture
    if path is None:
      return None
    buildroot = get_buildroot()
    # Ignore a couple of common cases. Note: If we support SCMs other than git in the future,
    # add their (top-level only) metadata dirs here if relevant.
    ignore = ['.git', os.path.relpath(self.get_options().pants_distdir, buildroot)]
    return Repro(path, buildroot, ignore)


class Repro(object):
  def __init__(self, path, buildroot, ignore):
    """Create a Repro instance.

    :param string path: Write the captured repro data to this path.
    :param string buildroot: Capture the workspace at this buildroot.
    :param ignore: Ignore these top-level files/dirs under buildroot.
    """
    if os.path.realpath(os.path.expanduser(path)).startswith(buildroot):
      raise ReproError('Repro capture file location must be outside the build root.')
    if not path.endswith('tar.gz') and not path.endswith('.tgz'):
      path += '.tar.gz'
    if os.path.exists(path):
      raise ReproError('Repro capture file already exists: {}'.format(path))
    self._path = path
    self._buildroot = buildroot
    self._ignore = ignore

  def capture(self, run_info_dict):
    # Force the scm discovery logging messages to appear before ours, so the startup delay
    # is properly associated in the user's mind with us and not with scm.
    logger.info('Capturing repro information to {}'.format(self._path))
    with open_tar(self._path, 'w:gz', dereference=True, compresslevel=6) as tarout:
      for relpath in os.listdir(self._buildroot):
        if relpath not in self._ignore:
          tarout.add(os.path.join(self._buildroot, relpath), relpath)

      with temporary_file() as tmpfile:
        tmpfile.write('# Pants repro captured for the following build:\n')
        for k, v in sorted(run_info_dict.items()):
          tmpfile.write('#  {}: {}\n'.format(k, v))
        cmd_line = list(sys.argv)
        # Use 'pants' instead of whatever the full executable path was on the user's system.
        cmd_line[0] = 'pants'
        # Remove any repro-related flags. The repro-ing user won't want to call those.
        cmd_line = [x for x in cmd_line if not x.startswith('--repro-')]
        tmpfile.write("'" +"' '".join(cmd_line) + "'\n")
        tmpfile.flush()
        chmod_plus_x(tmpfile.name)
        tarout.add(tmpfile.name, 'repro.sh')

  def log_location_of_repro_file(self):
    if not self._path:
      return  # No repro requested.
    logger.info('Captured repro information to {}'.format(self._path))
