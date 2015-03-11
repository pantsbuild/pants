# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import os
import subprocess
import traceback

from pants.scm.scm import Scm


class Git(Scm):
  """An Scm implementation backed by git."""

  @classmethod
  def detect_worktree(cls, binary='git'):
    """Detect the git working tree above cwd and return it; else, return None.

    binary: The path to the git binary to use, 'git' by default.
    """
    cmd = [binary, 'rev-parse', '--show-toplevel']
    try:
      process, out = cls._invoke(cmd)
      cls._check_result(cmd, process.returncode, raise_type=Scm.ScmException)
    except Scm.ScmException:
      return None
    return cls._cleanse(out)

  @classmethod
  def _invoke(cls, cmd):
    """Invoke the given command, and return a tuple of process and raw binary output.

    stderr flows to wherever its currently mapped for the parent process - generally to
    the terminal where the user can see the error.

    :param list cmd: The command in the form of a list of strings
    :returns: The completed process object and its standard output.
    :raises: Scm.LocalException if there was a problem exec'ing the command at all.
    """
    try:
      process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    except OSError as e:
      # Binary DNE or is not executable
      raise cls.LocalException('Failed to execute command {}: {}'.format(' '.join(cmd), e))
    out, _ = process.communicate()
    return process, out

  @classmethod
  def _cleanse(cls, output, errors='strict'):
    return output.strip().decode('utf-8', errors=errors)

  @classmethod
  def _check_result(cls, cmd, result, failure_msg=None, raise_type=Scm.ScmException):
    if result != 0:
      raise raise_type(failure_msg or '{} failed with exit code {}'.format(' '.join(cmd), result))

  def __init__(self, binary='git', gitdir=None, worktree=None, remote=None, branch=None, log=None):
    """Creates a git scm proxy that assumes the git repository is in the cwd by default.

    binary:    The path to the git binary to use, 'git' by default.
    gitdir:    The path to the repository's git metadata directory (typically '.git').
    worktree:  The path to the git repository working tree directory (typically '.').
    remote:    The default remote to use.
    branch:    The default remote branch to use.
    log:       A log object that supports debug, info, and warn methods.
    """
    super(Scm, self).__init__()

    self._gitcmd = binary
    self._worktree = os.path.realpath(worktree or os.getcwd())
    self._gitdir = os.path.realpath(gitdir) if gitdir else os.path.join(self._worktree, '.git')
    self._remote = remote
    self._branch = branch

    if log:
      self._log = log
    else:
      import logging
      self._log = logging.getLogger(__name__)

  def current_rev_identifier(self):
    return 'HEAD'

  @property
  def commit_id(self):
    return self._check_output(['rev-parse', 'HEAD'], raise_type=Scm.LocalException)

  @property
  def server_url(self):
    git_output = self._check_output(['remote', '--verbose'], raise_type=Scm.LocalException)
    origin_push_line = [line.split()[1] for line in git_output.splitlines()
                                        if 'origin' in line and '(push)' in line]
    if len(origin_push_line) != 1:
      raise Scm.LocalException('Unable to find origin remote amongst: ' + git_output)
    return origin_push_line[0]

  @property
  def tag_name(self):
    tag = self._check_output(['describe', '--tags', '--always'], raise_type=Scm.LocalException)
    return None if b'cannot' in tag else tag

  @property
  def branch_name(self):
    branch = self._check_output(['rev-parse', '--abbrev-ref', 'HEAD'],
                                raise_type=Scm.LocalException)
    return None if branch == 'HEAD' else branch

  def fix_git_relative_path(self, worktree_path, relative_to):
    return os.path.relpath(os.path.join(self._worktree, worktree_path), relative_to)

  def changed_files(self, from_commit=None, include_untracked=False, relative_to=None):
    relative_to = relative_to or self._worktree
    rel_suffix = ['--', relative_to]
    uncommitted_changes = self._check_output(['diff', '--name-only', 'HEAD'] + rel_suffix,
                                             raise_type=Scm.LocalException)

    files = set(uncommitted_changes.split())
    if from_commit:
      # Grab the diff from the merge-base to HEAD using ... syntax.  This ensures we have just
      # the changes that have occurred on the current branch.
      committed_cmd = ['diff', '--name-only', from_commit + '...HEAD'] + rel_suffix
      committed_changes = self._check_output(committed_cmd,
                                             raise_type=Scm.LocalException)
      files.update(committed_changes.split())
    if include_untracked:
      untracked_cmd = ['ls-files', '--other', '--exclude-standard'] + rel_suffix
      untracked = self._check_output(untracked_cmd,
                                     raise_type=Scm.LocalException)
      files.update(untracked.split())
    # git will report changed files relative to the worktree: re-relativize to relative_to
    return set(self.fix_git_relative_path(f, relative_to) for f in files)

  def changes_in(self, diffspec, relative_to=None):
    relative_to = relative_to or self._worktree
    cmd = ['diff-tree', '--no-commit-id', '--name-only', '-r', diffspec]
    files = self._check_output(cmd, raise_type=Scm.LocalException).split()
    return set(self.fix_git_relative_path(f.strip(), relative_to) for f in files)

  def changelog(self, from_commit=None, files=None):
    # We force the log output encoding to be UTF-8 here since the user may have a git config that
    # overrides the git UTF-8 default log output encoding.
    args = ['log', '--encoding=UTF-8', '--no-merges', '--stat', '--find-renames', '--find-copies']
    if from_commit:
      args.append(from_commit + '..HEAD')
    if files:
      args.append('--')
      args.extend(files)

    # There are various circumstances that can lead to git logs that are not transcodeable to utf-8,
    # for example: http://comments.gmane.org/gmane.comp.version-control.git/262685
    # Git will not error in these cases and we do not wish to either.  Here we direct byte sequences
    # that can not be utf-8 decoded to be replaced with the utf-8 replacement character.
    return self._check_output(args, raise_type=Scm.LocalException, errors='replace')

  def merge_base(self, left='master', right='HEAD'):
    """Returns the merge-base of master and HEAD in bash: `git merge-base left right`"""
    return self._check_output(['merge-base', left, right], raise_type=Scm.LocalException)

  def refresh(self, leave_clean=False):
    """Attempt to pull-with-rebase from upstream.  This is implemented as fetch-plus-rebase
       so that we can distinguish between errors in the fetch stage (likely network errors)
       and errors in the rebase stage (conflicts).  If leave_clean is true, then in the event
       of a rebase failure, the branch will be rolled back.  Otherwise, it will be left in the
       conflicted state.
    """
    remote, merge = self._get_upstream()
    self._check_call(['fetch', '--tags', remote, merge], raise_type=Scm.RemoteException)
    try:
      self._check_call(['rebase', 'FETCH_HEAD'], raise_type=Scm.LocalException)
    except Scm.LocalException as e:
      if leave_clean:
        self._log.debug('Cleaning up after failed rebase')
        try:
          self._check_call(['rebase', '--abort'], raise_type=Scm.LocalException)
        except Scm.LocalException as abort_exc:
          self._log.debug('Failed to up after failed rebase')
          self._log.debug(traceback.format_exc(abort_exc))
          # But let the original exception propagate, since that's the more interesting one
      raise e

  def tag(self, name, message=None):
    # We use -a here instead of --annotate to maintain maximum git compatibility.
    # --annotate was only introduced in 1.7.8 via:
    #   https://github.com/git/git/commit/c97eff5a95d57a9561b7c7429e7fcc5d0e3a7f5d
    self._check_call(['tag', '-a', '--message=' + (message or ''), name],
                     raise_type=Scm.LocalException)
    self.push('refs/tags/' + name)

  def commit(self, message):
    self._check_call(['commit', '--all', '--message=' + message], raise_type=Scm.LocalException)

  def commit_date(self, commit_reference):
    return self._check_output(['log', '-1', '--pretty=tformat:%ci', commit_reference],
                              raise_type=Scm.LocalException)

  def push(self, *refs):
    remote, merge = self._get_upstream()
    self._check_call(['push', remote, merge] + list(refs), raise_type=Scm.RemoteException)

  def _get_upstream(self):
    """Return the remote and remote merge branch for the current branch"""
    if not self._remote or not self._branch:
      branch = self.branch_name
      if not branch:
        raise Scm.LocalException('Failed to determine local branch')

      def get_local_config(key):
        value = self._check_output(['config', '--local', '--get', key],
                                   raise_type=Scm.LocalException)
        return value.strip()

      self._remote = self._remote or get_local_config('branch.{}.remote'.format(branch))
      self._branch = self._branch or get_local_config('branch.{}.merge'.format(branch))
    return self._remote, self._branch

  def _check_call(self, args, failure_msg=None, raise_type=None):
    cmd = self._create_git_cmdline(args)
    self._log_call(cmd)
    result = subprocess.call(cmd)
    self._check_result(cmd, result, failure_msg, raise_type)

  def _check_output(self, args, failure_msg=None, raise_type=None, errors='strict'):
    cmd = self._create_git_cmdline(args)
    self._log_call(cmd)

    process, out = self.\
      _invoke(cmd)

    self._check_result(cmd, process.returncode, failure_msg, raise_type)
    return self._cleanse(out, errors=errors)

  def _create_git_cmdline(self, args):
    return [self._gitcmd, '--git-dir=' + self._gitdir, '--work-tree=' + self._worktree] + args

  def _log_call(self, cmd):
    self._log.debug('Executing: ' + ' '.join(cmd))
