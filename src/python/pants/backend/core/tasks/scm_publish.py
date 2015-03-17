# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re
from abc import abstractmethod

from pants.base.deprecated import deprecated
from pants.base.exceptions import TaskError
from pants.option.options import Options
from pants.scm.scm import Scm


class Version(object):
  @staticmethod
  def parse(version):
    """Attempts to parse the given string as Semver, then falls back to Namedver."""
    try:
      return Semver.parse(version)
    except ValueError:
      return Namedver.parse(version)

  @abstractmethod
  def version(self):
    """Returns the string representation of this Version."""


class Namedver(Version):
  _VALID_NAME = re.compile('^[-_A-Za-z0-9]+$')

  @classmethod
  def parse(cls, version):
    # must not contain whitespace
    if not cls._VALID_NAME.match(version):
      raise ValueError("Named versions must be alphanumeric: '{0}'".format(version))
    # must not be valid semver
    try:
      Semver.parse(version)
    except ValueError:
      return Namedver(version)
    else:
      raise ValueError("Named versions must not be valid semantic versions: '{0}'".format(version))

  def __init__(self, version):
    self._version = version

  def version(self):
    return self._version

  def __eq__(self, other):
    return self._version == other._version

  def __cmp__(self, other):
    raise ValueError("{0} is not comparable to {1}".format(self, other))

  def __repr__(self):
    return 'Namedver({0})'.format(self.version())


class Semver(Version):
  @staticmethod
  def parse(version):
    components = version.split('.', 3)
    if len(components) != 3:
      raise ValueError
    major, minor, patch = components

    def to_i(component):
      try:
        return int(component)
      except (TypeError, ValueError):
        raise ValueError('Invalid revision component %s in %s - '
                         'must be an integer' % (component, version))
    return Semver(to_i(major), to_i(minor), to_i(patch))

  def __init__(self, major, minor, patch, snapshot=False):
    self.major = major
    self.minor = minor
    self.patch = patch
    self.snapshot = snapshot

  def bump(self):
    # A bump of a snapshot discards snapshot status
    return Semver(self.major, self.minor, self.patch + 1)

  def make_snapshot(self):
    return Semver(self.major, self.minor, self.patch, snapshot=True)

  def version(self):
    return '%s.%s.%s' % (
      self.major,
      self.minor,
      ('%s-SNAPSHOT' % self.patch) if self.snapshot else self.patch
    )

  def __eq__(self, other):
    return self.__cmp__(other) == 0

  def __cmp__(self, other):
    diff = self.major - other.major
    if not diff:
      diff = self.minor - other.minor
      if not diff:
        diff = self.patch - other.patch
        if not diff:
          if self.snapshot and not other.snapshot:
            diff = 1
          elif not self.snapshot and other.snapshot:
            diff = -1
          else:
            diff = 0
    return diff

  def __repr__(self):
    return 'Semver(%s)' % self.version()


class ScmPublishMixin(object):
  """A mixin for tasks that provides methods for publishing pushdbs via scm.

  Requires that the mixing task class
  * has the properties scm and log,
  * has the method get_options
  * calls register_scm_publish_options in its register_options definition
  """

  _SCM_PUSH_ATTEMPTS = 5

  @classmethod
  def register_scm_publish_options(cls, register):
    register('--scm-push-attempts', type=int, default=cls._SCM_PUSH_ATTEMPTS,
             help='Try pushing the pushdb to the SCM this many times before aborting.')
    register('--restrict-push-branches', advanced=True, type=Options.list,
             help='Allow pushes only from one of these branches.')

  @property
  def restrict_push_branches(self):
    return self.get_options().restrict_push_branches

  @property
  def scm_push_attempts(self):
    return self.get_options().scm_push_attempts

  def check_clean_master(self, commit=False):
    """Check for uncommitted tracked files and ensure on an allowed branch.

    :raise TaskError: on failure"""
    if commit:
      if self.restrict_push_branches:
        branch = self.scm.branch_name
        if branch not in self.restrict_push_branches:
          raise TaskError('Can only push from {}, currently on branch: {}'.format(
            ' '.join(sorted(self.restrict_push_branches)), branch
          ))

      changed_files = self.scm.changed_files()
      if changed_files:
        raise TaskError('Can only push from a clean branch, found : {}'.format(' '.join(changed_files)))
    else:
      self.log.info('Skipping check for a clean {} branch in test mode.'.format(self.scm.branch_name))

  def commit_pushdb(self, coordinates):
    """Commit changes to the pushdb with a message containing the provided coordinates."""
    self.scm.commit('pants build committing publish data for push of {}'.format(coordinates))

  def publish_pushdb_changes_to_remote_scm(self, pushdb_file, coordinate, tag_name, tag_message):
    """Push the pushdb changes to the remote scm repository, and then tag the commit if it succeeds
    """

    self._add_pushdb(pushdb_file)
    self.commit_pushdb(coordinate)
    self._push_and_tag_changes(
      attempts=self.scm_push_attempts,
      tag_name=tag_name,
      tag_message=tag_message
    )

  def _add_pushdb(self, pushdb_file):
    self.scm.add([pushdb_file])

  def _push_and_tag_changes(self, attempts, tag_name, tag_message):
    self._push_with_retry(self.scm, self.log, self.scm_push_attempts)
    self.scm.tag(tag_name, tag_message)

  @staticmethod
  def _push_with_retry(scm, log, attempts):
    scm_exception = None
    for attempt in range(attempts):
      try:
        log.debug("Trying scm push")
        scm.push()
        break # success
      except Scm.RemoteException as scm_exception:
        log.debug("Scm push failed, trying to refresh.")
        # This might fail in the event that there is a real conflict, throwing
        # a Scm.LocalException (in case of a rebase failure) or a Scm.RemoteException
        # in the case of a fetch failure.  We'll directly raise a local exception,
        # since we can't fix it by retrying, but if we do, we want to display the
        # remote exception that caused the refresh as well just in case the user cares.
        # Remote exceptions probably indicate network or configuration issues, so
        # we'll let them propagate
        try:
          scm.refresh(leave_clean=True)
        except Scm.LocalException as local_exception:
          exc = traceback.format_exc(scm_exception)
          log.debug("SCM exception while pushing: {}".format(exc))
          raise local_exception

    else:
      raise scm_exception

class ScmPublish(ScmPublishMixin):
  @deprecated('0.0.30', hint_message='Use ScmPublishMixin instead.')
  def __init__(self, scm, restrict_push_branches):
    self._restrict_push_branches = frozenset(restrict_push_branches or ())
    self.scm = scm
    self.log = self.context.log

  @property
  def restrict_push_branches(self):
    return self._restrict_push_branches

  @property
  def scm_push_attempts(self):
    return ScmPublishMixin._SCM_PUSH_ATTEMPTS
