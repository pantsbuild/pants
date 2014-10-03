# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from abc import abstractmethod
import re

from pants.base.exceptions import TaskError

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


class ScmPublish(object):
  def __init__(self, scm, restrict_push_branches):
    self.restrict_push_branches = frozenset(restrict_push_branches or ())
    self.scm = scm

  def check_clean_master(self, commit=False):
    if commit:
      if self.restrict_push_branches:
        branch = self.scm.branch_name
        if branch not in self.restrict_push_branches:
          raise TaskError('Can only push from %s, currently on branch: %s' % (
            ' '.join(sorted(self.restrict_push_branches)), branch
          ))

      changed_files = self.scm.changed_files()
      if changed_files:
        raise TaskError('Can only push from a clean branch, found : %s' % ' '.join(changed_files))
    else:
      print('Skipping check for a clean %s in test mode.' % self.scm.branch_name)

  def commit_pushdb(self, coordinates):
    self.scm.commit('pants build committing publish data for push of %s' % coordinates)
