# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re
import subprocess
from contextlib import contextmanager
from itertools import izip_longest

from pants.scm.git import Git
from pants.util.contextutil import environment_as
from pants.util.dirutil import safe_mkdtemp, safe_rmtree


class Version(object):

  def __init__(self, text):
    self._components = map(int, text.split('.'))

  def __cmp__(self, other):
    for ours, theirs in izip_longest(self._components, other._components, fillvalue=0):
      difference = cmp(ours, theirs)
      if difference != 0:
        return difference
    return 0


def git_version():
  """Get a Version() based on installed command-line git's version"""
  process = subprocess.Popen(['git', '--version'], stdout=subprocess.PIPE)
  (stdout, stderr) = process.communicate()
  assert process.returncode == 0, "Failed to determine git version."
  # stdout is like 'git version 1.9.1.598.g9119e8b\n'  We want '1.9.1.598'
  matches = re.search(r'\s(\d+(?:\.\d+)*)[\s\.]', stdout)
  return Version(matches.group(1))


@contextmanager
def initialize_repo(worktree):
  """Initialize git repository for the given worktree."""
  gitdir = safe_mkdtemp()
  with environment_as(GIT_DIR=gitdir, GIT_WORK_TREE=worktree):
    subprocess.check_call(['git', 'init'])
    subprocess.check_call(['git', 'config', 'user.email', 'you@example.com'])
    subprocess.check_call(['git', 'config', 'user.name', 'Your Name'])
    subprocess.check_call(['git', 'add', '.'])
    subprocess.check_call(['git', 'commit', '-am', 'Add project files.'])

    yield Git(gitdir=gitdir, worktree=worktree)

    safe_rmtree(gitdir)
