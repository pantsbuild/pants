# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.goal.products import UnionProducts


class ClasspathEntry(object):
  def __init__(self, path):
    self.path = path

  def is_excluded_by(self, excludes):
    return False

  def __hash__(self):
    return hash(self.path)

  def __eq__(self, other):
    return isinstance(other, ClasspathEntry) and self.path == other.path

  def __ne__(self, other):
    return not self == other


# TODO(John Sirois): An ArtifactClasspathEntry is a Resolved jar - merge.
class ArtifactClasspathEntry(ClasspathEntry):
  def __init__(self, resolved_jar):
    super(ArtifactClasspathEntry, self).__init__(resolved_jar.pants_path)
    self.coordinate = resolved_jar.coordinate
    self.cache_path = resolved_jar.cache_path

  def is_excluded_by(self, excludes):
    return any(_matches_exclude(self.coordinate, exclude) for exclude in excludes)

  def __hash__(self):
    return hash((self.path, self.coordinate, self.cache_path))

  def __eq__(self, other):
    return (isinstance(other, ArtifactClasspathEntry) and
            self.path == other.path and
            self.coordinate == other.coordinate and
            self.cache_path == other.cache_path)

  def __ne__(self, other):
    return not self == other


def _matches_exclude(coordinate, exclude):
  return exclude.org == coordinate.org and (exclude.name or coordinate.name) == coordinate.name


def _not_excluded_filter(excludes):
  def not_excluded(path_tuple):
    conf, classpath_entry = path_tuple
    return not classpath_entry.is_excluded_by(excludes)
  return not_excluded


class ClasspathProducts(object):
  def __init__(self):
    self._classpaths = UnionProducts()
    self._excludes = UnionProducts()
    self._buildroot = get_buildroot()

  def add_for_targets(self, targets, classpath_elements):
    """Adds classpath path elements to the products of all the provided targets."""
    for target in targets:
      self.add_for_target(target, classpath_elements)

  def add_for_target(self, target, classpath_elements):
    """Adds classpath path elements to the products of the provided target."""
    self._add_elements_for_target(target, self._wrap_path_elements(classpath_elements))

  def add_jars_for_targets(self, targets, conf, resolved_jars):
    """Adds jar classpath elements to the products of the provided targets.

    The resolved jars are added in a way that works with excludes.
    """
    classpath_entries = []
    for jar in resolved_jars:
      if not jar.pants_path:
        raise TaskError('Jar: {!s} has no specified path.'.format(jar.coordinate))
      classpath_entries.append((conf, ArtifactClasspathEntry(jar)))

    for target in targets:
      self._add_elements_for_target(target, classpath_entries)

  def add_excludes_for_targets(self, targets):
    """Add excludes from the provided targets.

    Does not look up transitive excludes.
    """
    for target in targets:
      self._add_excludes_for_target(target)

  def remove_for_target(self, target, classpath_elements):
    """Removes the given entries for the target."""
    self._classpaths.remove_for_target(target, self._wrap_path_elements(classpath_elements))

  def get_for_target(self, target, transitive=True):
    """Gets the transitive classpath products for the given target.

    Products are returned in order, respecting target excludes.

    :param target: The target to lookup classpath products for.
    :param bool transitive: `True` to include the transitive classpath for the target, `False` to
                            just include the classpath formed by the direct dependencies of the
                            target.
    :returns: The ordered (conf, path) tuples, with paths being either classfile directories or
              jars.
    :rtype: list of (string, string)
    """
    return self.get_for_targets([target], transitive=transitive)

  def get_for_targets(self, targets, transitive=True):
    """Gets the transitive classpath products for the given targets.

    Products are returned in order, respecting target excludes.

    :param targets: The targets to lookup classpath products for.
    :param bool transitive: `True` to include the transitive classpath for all targets, `False` to
                            just include the classpath formed by the direct dependencies of the
                            targets.
    :returns: The ordered (conf, path) tuples, with paths being either classfile directories or
              jars.
    :rtype: list of (string, string)
    """
    cp_entries = self.get_classpath_entries_for_targets(targets, transitive=transitive)
    return [(conf, cp_entry.path) for conf, cp_entry in cp_entries]

  def get_classpath_entries_for_targets(self, targets, transitive=True, respect_excludes=True):
    """Gets the transitive classpath products for the given targets.

    Products are returned in order, optionally respecting target excludes.

    :param targets: The targets to lookup classpath products for.
    :param bool transitive: `True` to include the transitive classpath for all targets, `False` to
                            just include the classpath formed by the direct dependencies of the
                            targets.
    :param bool respect_excludes: `True` to respect excludes; `False` to ignore them.
    :returns: The ordered (conf, classpath entry) tuples.
    :rtype: list of (string, :class:`ClasspathEntry`)
    """
    classpath_tuples = self._classpaths.get_for_targets(targets, transitive)
    if respect_excludes:
      return self._filter_by_excludes(classpath_tuples, targets, transitive)
    else:
      return classpath_tuples

  def _filter_by_excludes(self, classpath_tuples, root_targets, transitive):
    excludes = self._excludes.get_for_targets(root_targets, transitive=transitive)
    return filter(_not_excluded_filter(excludes),
                  classpath_tuples)

  def _add_excludes_for_target(self, target):
    if target.is_exported:
      self._excludes.add_for_target(target, [Exclude(target.provides.org,
                                                     target.provides.name)])
    if isinstance(target, JvmTarget) and target.excludes:
      self._excludes.add_for_target(target, target.excludes)

  def _wrap_path_elements(self, classpath_elements):
    return [(element[0], ClasspathEntry(element[1])) for element in classpath_elements]

  def _add_elements_for_target(self, target, elements):
    self._validate_classpath_tuples(elements, target)
    self._classpaths.add_for_target(target, elements)

  def _validate_classpath_tuples(self, classpath, target):
    """Validates that all files are located within the working copy, to simplify relativization.

    :param classpath: The list of classpath tuples. Each tuple is a 2-tuple of ivy_conf and ClasspathEntry
    :param target: The target that the classpath tuple is being registered for
    :raises: `TaskError` when the path is outside the build root
    """
    for classpath_tuple in classpath:
      conf, classpath_entry = classpath_tuple
      path = classpath_entry.path
      if os.path.relpath(path, self._buildroot).startswith(os.pardir):
        raise TaskError(
          'Classpath entry {} for target {} is located outside the buildroot.'
          .format(path, target.address.spec))
