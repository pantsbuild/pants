# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import getpass
import os
import re
import socket
import time

from pants import version
from pants.base.build_environment import get_buildroot, get_scm
from pants.util.dirutil import safe_mkdir_for


class RunInfo(object):
  """A little plaintext file containing very basic info about a pants run.

  Can only be appended to, never edited.
  """

  def __init__(self, info_file):
    self._info_file = info_file
    safe_mkdir_for(self._info_file)
    self._info = {}
    if os.path.exists(self._info_file):
      with open(self._info_file, 'r') as infile:
        info = infile.read()
      for m in re.finditer("""^([^:]+):(.*)$""", info, re.MULTILINE):
        self._info[m.group(1).strip()] = m.group(2).strip()

  def path(self):
    return self._info_file

  def get_info(self, key):
    return self._info.get(key, None)

  def __getitem__(self, key):
    ret = self.get_info(key)
    if ret is None:
      raise KeyError(key)
    return ret

  def get_as_dict(self):
    return self._info.copy()

  def add_info(self, key, val, ignore_errors=False):
    """Adds the given info and returns a dict composed of just this added info."""
    self.add_infos((key, val), ignore_errors=ignore_errors)

  def add_infos(self, *keyvals, **kwargs):
    """Adds the given info and returns a dict composed of just this added info."""
    infos = dict(keyvals)
    kv_pairs = []
    for key, val in infos.items():
      key = key.strip()
      val = str(val).strip()
      if ':' in key:
        raise ValueError('info key "{}" must not contain a colon.'.format(key))
      kv_pairs.append((key, val))

    for k, v in kv_pairs:
      if k in self._info:
        raise ValueError('info key "{}" already exists with value {}. '
                         'Cannot add it again with value {}.'.format(k, self._info[k], v))
      self._info[k] = v

    try:
      with open(self._info_file, 'a') as outfile:
        for k, v in kv_pairs:
          outfile.write('{}: {}\n'.format(k, v))
    except IOError:
      if not kwargs.get('ignore_errors', False):
        raise

  def add_basic_info(self, run_id, timestamp):
    """Adds basic build info."""
    datetime = time.strftime('%A %b %d, %Y %H:%M:%S', time.localtime(timestamp))
    user = getpass.getuser()
    machine = socket.gethostname()
    buildroot = get_buildroot()
    # TODO: Get rid of the redundant 'path' key once everyone is off it.
    self.add_infos(('id', run_id), ('timestamp', timestamp), ('datetime', datetime),
                   ('user', user), ('machine', machine), ('path', buildroot),
                   ('buildroot', buildroot), ('version', version.VERSION))

  def add_scm_info(self):
    """Adds SCM-related info."""
    scm = get_scm()
    if scm:
      revision = scm.commit_id
      tag = scm.tag_name or 'none'
      branch = scm.branch_name or revision
    else:
      revision, tag, branch = 'none', 'none', 'none'
    self.add_infos(('revision', revision), ('tag', tag), ('branch', branch))
