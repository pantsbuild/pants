# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

from twitter.common.collections import OrderedSet

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.base.exceptions import TaskError
from pants.build_graph.build_graph import BuildGraph
from pants.goal.products import UnionProducts
from pants.java.jar.exclude import Exclude
from pants.util.dirutil import safe_delete, safe_open


class ClasspathEntry(object):
  """Represents a java classpath entry.

  :API: public
  """

  def __init__(self, path):
    self._path = path

  @property
  def path(self):
    """Returns the pants internal path of this classpath entry.

    Suitable for use in constructing classpaths for pants executions and pants generated artifacts.

    :API: public

    :rtype: string
    """
    return self._path

  def is_excluded_by(self, excludes):
    """Returns `True` if this classpath entry should be excluded given the `excludes` in play.

    :param excludes: The excludes to check this classpath entry against.
    :type excludes: list of :class:`pants.backend.jvm.targets.exclude.Exclude`
    :rtype: bool
    """
    return False

  def __hash__(self):
    return hash(self.path)

  def __eq__(self, other):
    return isinstance(other, ClasspathEntry) and self.path == other.path

  def __ne__(self, other):
    return not self == other

  def __repr__(self):
    return 'ClasspathEntry(path={!r})'.format(self.path)

  @classmethod
  def is_artifact_classpath_entry(cls, classpath_entry):
    """
    :API: public
    """
    return isinstance(classpath_entry, ArtifactClasspathEntry)

  @classmethod
  def is_internal_classpath_entry(cls, classpath_entry):
    """
    :API: public
    """
    return not cls.is_artifact_classpath_entry(classpath_entry)


class ArtifactClasspathEntry(ClasspathEntry):
  """Represents a resolved third party classpath entry.

  :API: public
  """

  def __init__(self, path, coordinate, cache_path):
    super(ArtifactClasspathEntry, self).__init__(path)
    self._coordinate = coordinate
    self._cache_path = cache_path

  @property
  def coordinate(self):
    """Returns the maven coordinate that used to resolve this classpath entry's artifact.

    :rtype: :class:`pants.java.jar.M2Coordinate`
    """
    return self._coordinate

  @property
  def cache_path(self):
    """Returns the external cache path of this classpath entry.

    For example, the `~/.m2/repository` or `~/.ivy2/cache` location of the resolved artifact for
    maven and ivy resolvers respectively.

    Suitable for use in constructing classpaths for external tools that should not be subject to
    potential volatility in pants own internal caches.

    :API: public

    :rtype: string
    """
    return self._cache_path

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

  def __repr__(self):
    return ('ArtifactClasspathEntry(path={!r}, coordinate={!r}, cache_path={!r})'
            .format(self.path, self.coordinate, self.cache_path))


def _matches_exclude(coordinate, exclude):
  if not coordinate.org == exclude.org:
    return False

  if not exclude.name:
    return True
  if coordinate.name == exclude.name:
    return True
  return False


def _not_excluded_filter(excludes):
  def not_excluded(product_to_target):
    path_tuple = product_to_target[0]
    conf, classpath_entry = path_tuple
    return not classpath_entry.is_excluded_by(excludes)
  return not_excluded


class MissingClasspathEntryError(Exception):
  """Indicates an unexpected problem finding a classpath entry."""


class ClasspathProducts(object):
  """
  :API: public
  """

  def __init__(self, pants_workdir, classpaths=None, excludes=None):
    self._classpaths = classpaths or UnionProducts()
    self._excludes = excludes or UnionProducts()
    self._pants_workdir = pants_workdir

  @staticmethod
  def init_func(pants_workdir):
    """
    :API: public
    """
    return lambda: ClasspathProducts(pants_workdir)

  @classmethod
  def create_canonical_classpath(cls, classpath_products, targets, basedir,
                                 save_classpath_file=False,
                                 internal_classpath_only=True,
                                 excludes=None):
    """Create a stable classpath of symlinks with standardized names.

    By default symlinks are created for each target under `basedir` based on its `target.id`.
    Unique suffixes are added to further disambiguate classpath products from the same target.

    It also optionally saves the classpath products to be used externally (by intellij plugin),
    one output file for each target.

    Note calling this function will refresh the symlinks and output files for the target under
    `basedir` if they exist, but it will NOT delete/cleanup the contents for *other* targets.
    Caller wants that behavior can make the similar calls for other targets or just remove
    the `basedir` first.

    :param classpath_products: Classpath products.
    :param targets: Targets to create canonical classpath for.
    :param basedir: Directory to create symlinks.
    :param save_classpath_file: An optional file with original classpath entries that symlinks
      are created from.
    :param internal_classpath_only: whether to create symlinks just for internal classpath or
       all classpath.
    :param excludes: classpath entries should be excluded.

    :returns: Converted canonical classpath.
    :rtype: list of strings
    """
    def delete_old_target_output_files(classpath_prefix):
      """Delete existing output files or symlinks for target."""
      directory, basename = os.path.split(classpath_prefix)
      pattern = re.compile(r'^{basename}(([0-9]+)(\.jar)?|classpath\.txt)$'
                           .format(basename=re.escape(basename)))
      files = [filename for filename in os.listdir(directory) if pattern.match(filename)]
      for rel_path in files:
        path = os.path.join(directory, rel_path)
        if os.path.islink(path) or os.path.isfile(path):
          safe_delete(path)

    def prepare_target_output_folder(basedir, target):
      """Prepare directory that will contain canonical classpath for the target.

      This includes creating directories if it does not already exist, cleaning up
      previous classpath output related to the target.
      """
      output_dir = basedir
      # TODO(peiyu) improve readability once we deprecate the old naming style.
      # For example, `-` is commonly placed in string format as opposed to here.
      classpath_prefix_for_target = '{basedir}/{target_id}-'.format(basedir=basedir,
                                                                    target_id=target.id)

      if os.path.exists(output_dir):
        delete_old_target_output_files(classpath_prefix_for_target)
      else:
        os.makedirs(output_dir)
      return classpath_prefix_for_target

    excludes = excludes or set()
    canonical_classpath = []
    target_to_classpath = ClasspathUtil.classpath_by_targets(targets, classpath_products)

    processed_entries = set()
    for target, classpath_entries_for_target in target_to_classpath.items():
      if internal_classpath_only:
        classpath_entries_for_target = filter(ClasspathEntry.is_internal_classpath_entry,
                                              classpath_entries_for_target)
      if len(classpath_entries_for_target) > 0:
        classpath_prefix_for_target = prepare_target_output_folder(basedir, target)

        # Note: for internal targets pants has only one classpath entry, but user plugins
        # might generate additional entries, for example, build.properties for the target.
        # Also it's common to have multiple classpath entries associated with 3rdparty targets.
        for (index, entry) in enumerate(classpath_entries_for_target):
          if entry.is_excluded_by(excludes):
            continue

          # Avoid creating symlink for the same entry twice, only the first entry on
          # classpath will get a symlink. The resulted symlinks as a whole are still stable,
          # but may have non-consecutive suffixes because the 'missing' ones are those
          # have already been created symlinks by previous targets.
          if entry in processed_entries:
            continue
          processed_entries.add(entry)

          # Create a unique symlink path by prefixing the base file name with a monotonic
          # increasing `index` to avoid name collisions.
          _, ext = os.path.splitext(entry.path)
          symlink_path = '{}{}{}'.format(classpath_prefix_for_target, index, ext)
          real_entry_path = os.path.realpath(entry.path)
          if not os.path.exists(real_entry_path):
            raise MissingClasspathEntryError('Could not find {realpath} when attempting to link '
                                             '{src} into {dst}'
                                             .format(realpath=real_entry_path, src=entry.path, dst=symlink_path))

          os.symlink(real_entry_path, symlink_path)
          canonical_classpath.append(symlink_path)

        if save_classpath_file:
          classpath = [entry.path for entry in classpath_entries_for_target]
          with safe_open('{}classpath.txt'.format(classpath_prefix_for_target), 'wb') as classpath_file:
            classpath_file.write(os.pathsep.join(classpath).encode('utf-8'))
            classpath_file.write('\n')

    return canonical_classpath

  def copy(self):
    """Returns a copy of this ClasspathProducts.

    Edits to the copy's classpaths or exclude associations will not affect the classpaths or
    excludes in the original. The copy is shallow though, so edits to the the copy's product values
    will mutate the original's product values.  See `UnionProducts.copy`.

    :API: public

    :rtype: :class:`ClasspathProducts`
    """
    return ClasspathProducts(pants_workdir=self._pants_workdir,
                             classpaths=self._classpaths.copy(),
                             excludes=self._excludes.copy())

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
      cp_entry = ArtifactClasspathEntry(jar.pants_path, jar.coordinate, jar.cache_path)
      classpath_entries.append((conf, cp_entry))

    for target in targets:
      self._add_elements_for_target(target, classpath_entries)

  def add_excludes_for_targets(self, targets):
    """Add excludes from the provided targets.

    Does not look up transitive excludes.

    :param targets: The targets to add excludes for.
    :type targets: list of :class:`pants.build_graph.target.Target`
    """
    for target in targets:
      self._add_excludes_for_target(target)

  def remove_for_target(self, target, classpath_elements):
    """Removes the given entries for the target."""
    self._classpaths.remove_for_target(target, self._wrap_path_elements(classpath_elements))

  def get_for_target(self, target):
    """Gets the classpath products for the given target.

    Products are returned in order, respecting target excludes.

    :param target: The target to lookup classpath products for.
    :returns: The ordered (conf, path) tuples, with paths being either classfile directories or
              jars.
    :rtype: list of (string, string)
    """
    return self.get_for_targets([target])

  def get_for_targets(self, targets):
    """Gets the classpath products for the given targets.

    Products are returned in order, respecting target excludes.

    :param targets: The targets to lookup classpath products for.
    :returns: The ordered (conf, path) tuples, with paths being either classfile directories or
              jars.
    :rtype: list of (string, string)
    """
    cp_entries = self.get_classpath_entries_for_targets(targets)
    return [(conf, cp_entry.path) for conf, cp_entry in cp_entries]

  def get_classpath_entries_for_targets(self, targets, respect_excludes=True):
    """Gets the classpath products for the given targets.

    Products are returned in order, optionally respecting target excludes.

    :param targets: The targets to lookup classpath products for.
    :param bool respect_excludes: `True` to respect excludes; `False` to ignore them.
    :returns: The ordered (conf, classpath entry) tuples.
    :rtype: list of (string, :class:`ClasspathEntry`)
    """

    # remove the duplicate, preserve the ordering.
    return list(OrderedSet([cp for cp, target in self.get_product_target_mappings_for_targets(
                            targets, respect_excludes)]))

  def get_product_target_mappings_for_targets(self, targets, respect_excludes=True):
    """Gets the classpath products-target associations for the given targets.

    Product-target tuples are returned in order, optionally respecting target excludes.

    :param targets: The targets to lookup classpath products for.
    :param bool respect_excludes: `True` to respect excludes; `False` to ignore them.
    :returns: The ordered (classpath products, target) tuples.
    """
    classpath_target_tuples = self._classpaths.get_product_target_mappings_for_targets(targets)
    if respect_excludes:
      return self._filter_by_excludes(classpath_target_tuples, targets)
    else:
      return classpath_target_tuples

  def get_artifact_classpath_entries_for_targets(self, targets, respect_excludes=True):
    """Gets the artifact classpath products for the given targets.

    Products are returned in order, optionally respecting target excludes, and the products only
    include external artifact classpath elements (ie: resolved jars).

    :param targets: The targets to lookup classpath products for.
    :param bool respect_excludes: `True` to respect excludes; `False` to ignore them.
    :returns: The ordered (conf, classpath entry) tuples.
    :rtype: list of (string, :class:`ArtifactClasspathEntry`)
    """
    classpath_tuples = self.get_classpath_entries_for_targets(targets,
                                                              respect_excludes=respect_excludes)
    return [(conf, cp_entry) for conf, cp_entry in classpath_tuples
            if ClasspathEntry.is_artifact_classpath_entry(cp_entry)]

  def get_internal_classpath_entries_for_targets(self, targets, respect_excludes=True):
    """Gets the internal classpath products for the given targets.

    Products are returned in order, optionally respecting target excludes, and the products only
    include internal artifact classpath elements (ie: no resolved jars).

    :param targets: The targets to lookup classpath products for.
    :param bool respect_excludes: `True` to respect excludes; `False` to ignore them.
    :returns: The ordered (conf, classpath entry) tuples.
    :rtype: list of (string, :class:`ClasspathEntry`)
    """
    classpath_tuples = self.get_classpath_entries_for_targets(targets,
                                                              respect_excludes=respect_excludes)
    return [(conf, cp_entry) for conf, cp_entry in classpath_tuples
            if ClasspathEntry.is_internal_classpath_entry(cp_entry)]

  def update(self, other):
    """Adds the contents of other to this ClasspathProducts."""
    if self._pants_workdir != other._pants_workdir:
      raise ValueError('Other ClasspathProducts from a different pants workdir {}'.format(other._pants_workdir))
    for target, products in other._classpaths._products_by_target.items():
      self._classpaths.add_for_target(target, products)
    for target, products in other._excludes._products_by_target.items():
      self._excludes.add_for_target(target, products)

  def _filter_by_excludes(self, classpath_target_tuples, root_targets):
    # Excludes are always applied transitively, so regardless of whether a transitive
    # set of targets was included here, their closure must be included.
    closure = BuildGraph.closure(root_targets, bfs=True)
    excludes = self._excludes.get_for_targets(closure)
    return filter(_not_excluded_filter(excludes), classpath_target_tuples)

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
    """Validates that all files are located within the working directory, to simplify relativization.

    :param classpath: The list of classpath tuples. Each tuple is a 2-tuple of ivy_conf and
                      ClasspathEntry.
    :param target: The target that the classpath tuple is being registered for.
    :raises: `TaskError` when the path is outside the work directory
    """
    for classpath_tuple in classpath:
      conf, classpath_entry = classpath_tuple
      path = classpath_entry.path
      if os.path.relpath(path, self._pants_workdir).startswith(os.pardir):
        raise TaskError(
          'Classpath entry {} for target {} is located outside the working directory "{}".'
          .format(path, target.address.spec, self._pants_workdir))

  def __eq__(self, other):
    return (isinstance(other, ClasspathProducts) and
            self._pants_workdir == other._pants_workdir and
            self._classpaths == other._classpaths and
            self._excludes == other._excludes)

  def __ne__(self, other):
    return not self == other
