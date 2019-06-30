# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
import subprocess
from contextlib import contextmanager

from pants.base.revision import Revision
from pants.scm.git import Git
from pants.util.contextutil import environment_as, temporary_dir


MIN_REQUIRED_GIT_VERSION = Revision.semver('1.7.10')


def git_version():
  """Get a Version() based on installed command-line git's version"""
  process = subprocess.Popen(['git', '--version'], stdout=subprocess.PIPE)
  (stdout, stderr) = process.communicate()
  assert process.returncode == 0, "Failed to determine git version."
  # stdout is like 'git version 1.9.1.598.g9119e8b\n'  We want '1.9.1.598'
  matches = re.search(r'\s(\d+(?:\.\d+)*)[\s\.]', stdout.decode())
  return Revision.lenient(matches.group(1))


def get_repo_root():
  """Return the absolute path to the root directory of the Pants git repo."""
  return subprocess.check_output(['git', 'rev-parse', '--show-toplevel']).strip().decode()


@contextmanager
def initialize_repo(worktree, gitdir=None):
  """Initialize a git repository for the given `worktree`.

  NB: The given `worktree` must contain at least one file which will be committed to form an initial
  commit.

  :param string worktree: The path to the git work tree.
  :param string gitdir: An optional path to the `.git` dir to use.
  :returns: A `Git` repository object that can be used to interact with the repo.
  :rtype: :class:`pants.scm.git.Git`
  """
  @contextmanager
  def use_gitdir():
    if gitdir:
      yield gitdir
    else:
      with temporary_dir() as d:
        yield d

  with use_gitdir() as git_dir, environment_as(GIT_DIR=git_dir, GIT_WORK_TREE=worktree):
    subprocess.check_call(['git', 'init'])
    subprocess.check_call(['git', 'config', 'user.email', 'you@example.com'])
    # TODO: This method inherits the global git settings, so if a developer has gpg signing on, this
    # will turn that off. We should probably just disable reading from the global config somehow:
    # https://git-scm.com/docs/git-config.
    subprocess.check_call(['git', 'config', 'commit.gpgSign', 'false'])
    subprocess.check_call(['git', 'config', 'user.name', 'Your Name'])
    subprocess.check_call(['git', 'add', '.'])
    subprocess.check_call(['git', 'commit', '-am', 'Add project files.'])

    yield Git(gitdir=git_dir, worktree=worktree)
