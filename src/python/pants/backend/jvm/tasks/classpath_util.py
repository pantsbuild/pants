# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import os
import re
from collections import OrderedDict

from twitter.common.collections import OrderedSet

from pants.backend.jvm.tasks.classpath_products import ClasspathEntry
from pants.util.contextutil import open_zip
from pants.util.dirutil import fast_relpath, safe_delete, safe_open, safe_walk


class MissingClasspathEntryError(Exception):
  """Indicates an unexpected problem finding a classpath entry."""


class ClasspathUtil(object):

  @classmethod
  def compute_classpath(cls, targets, classpath_products, extra_classpath_tuples, confs):
    """Return the list of classpath entries for a classpath covering the passed targets.

    Filters and adds paths from extra_classpath_tuples to the end of the resulting list.

    :param targets: The targets to generate a classpath for.
    :param ClasspathProducts classpath_products: Product containing classpath elements.
    :param extra_classpath_tuples: Additional classpath entries.
    :param confs: The list of confs for use by this classpath.
    :returns: The classpath as a list of path elements.
    :rtype: list of string
    """
    classpath_iter = cls._classpath_iter(targets, classpath_products, confs=confs)
    total_classpath = OrderedSet(classpath_iter)

    filtered_extra_classpath_iter = cls._filtered_classpath_by_confs_iter(extra_classpath_tuples,
                                                                          confs)
    extra_classpath_iter = cls._entries_iter(filtered_extra_classpath_iter)
    total_classpath.update(extra_classpath_iter)
    return list(total_classpath)

  @classmethod
  def classpath(cls, targets, classpath_products, confs=('default',)):
    """Return the classpath as a list of paths covering all the passed targets.

    :param targets: Targets to build an aggregated classpath for.
    :param ClasspathProducts classpath_products: Product containing classpath elements.
    :param confs: The list of confs for use by this classpath.
    :returns: The classpath as a list of path elements.
    :rtype: list of string
    """
    classpath_iter = cls._classpath_iter(targets, classpath_products, confs=confs)
    return list(classpath_iter)

  @classmethod
  def _classpath_iter(cls, targets, classpath_products, confs=('default',)):
    classpath_tuples = classpath_products.get_for_targets(targets)
    filtered_tuples_iter = cls._filtered_classpath_by_confs_iter(classpath_tuples, confs)
    return cls._entries_iter(filtered_tuples_iter)

  @classmethod
  def internal_classpath(cls, targets, classpath_products, confs=('default',)):
    """Return the list of internal classpath entries for a classpath covering all `targets`.

    Any classpath entries contributed by external dependencies will be omitted.

    :param targets: Targets to build an aggregated classpath for.
    :param ClasspathProducts classpath_products: Product containing classpath elements.
    :param confs: The list of confs for use by this classpath.
    :returns: The classpath as a list of path elements.
    :rtype: list of string
    """
    classpath_tuples = classpath_products.get_internal_classpath_entries_for_targets(targets)
    filtered_tuples_iter = cls._filtered_classpath_by_confs_iter(classpath_tuples, confs)
    return [entry.path for entry in cls._entries_iter(filtered_tuples_iter)]

  @classmethod
  def classpath_by_targets(cls, targets, classpath_products, confs=('default',)):
    """Return classpath entries grouped by their targets for the given `targets`.

    :param targets: The targets to lookup classpath products for.
    :param ClasspathProducts classpath_products: Product containing classpath elements.
    :param confs: The list of confs for use by this classpath.
    :returns: The ordered (target, classpath) mappings.
    :rtype: OrderedDict
    """
    classpath_target_tuples = classpath_products.get_product_target_mappings_for_targets(targets)
    filtered_items_iter = itertools.ifilter(cls._accept_conf_filter(confs, lambda x: x[0][0]),
                                            classpath_target_tuples)

    # group (classpath_entry, target) tuples by targets
    target_to_classpath = OrderedDict()
    for classpath_entry, target in filtered_items_iter:
      _, entry = classpath_entry
      if not target in target_to_classpath:
        target_to_classpath[target] = []
      target_to_classpath[target].append(entry)
    return target_to_classpath

  @classmethod
  def _accept_conf_filter(cls, confs, unpack_func=None):
    def accept_conf_in_item(item):
      conf = unpack_func(item)
      return confs is None or conf in confs

    unpack_func = unpack_func or (lambda x: x)
    return accept_conf_in_item

  @classmethod
  def _filtered_classpath_by_confs_iter(cls, classpath_tuples, confs):
    filter_func = cls._accept_conf_filter(confs, unpack_func=lambda x: x[0])
    return itertools.ifilter(filter_func, classpath_tuples)

  @classmethod
  def _entries_iter(cls, classpath):
    for conf, entry in classpath:
      yield entry

  @classmethod
  def classpath_contents(cls, targets, classpath_products, confs=('default',)):
    """Provide a generator over the contents (classes/resources) of a classpath.

    :param targets: Targets to iterate the contents classpath for.
    :param ClasspathProducts classpath_products: Product containing classpath elements.
    :param confs: The list of confs for use by this classpath.
    :returns: An iterator over all classpath contents, one directory, class or resource relative
              path per iteration step.
    :rtype: :class:`collections.Iterator` of string
    """
    classpath_iter = cls._classpath_iter(targets, classpath_products, confs=confs)
    for f in cls.classpath_entries_contents(classpath_iter):
      yield f

  @classmethod
  def classpath_entries_contents(cls, classpath_entries):
    """Provide a generator over the contents (classes/resources) of a classpath.

    Subdirectories are included and differentiated via a trailing forward slash (for symmetry
    across ZipFile.namelist and directory walks).

    :param classpath_entries: A sequence of classpath_entries. Non-jars/dirs are ignored.
    :returns: An iterator over all classpath contents, one directory, class or resource relative
              path per iteration step.
    :rtype: :class:`collections.Iterator` of string
    """
    for entry in classpath_entries:
      if cls.is_jar(entry):
        # Walk the jar namelist.
        with open_zip(entry, mode='r') as jar:
          for name in jar.namelist():
            yield name
      elif os.path.isdir(entry):
        # Walk the directory, including subdirs.
        def rel_walk_name(abs_sub_dir, name):
          return fast_relpath(os.path.join(abs_sub_dir, name), entry)
        for abs_sub_dir, dirnames, filenames in safe_walk(entry):
          for name in dirnames:
            yield '{}/'.format(rel_walk_name(abs_sub_dir, name))
          for name in filenames:
            yield rel_walk_name(abs_sub_dir, name)
      else:
        # non-jar and non-directory classpath entries should be ignored
        pass

  @classmethod
  def classname_for_rel_classfile(cls, class_file_name):
    """Return the class name for the given relative-to-a-classpath-entry file, or None."""
    if not class_file_name.endswith('.class'):
      return None
    return class_file_name[:-len('.class')].replace('/', '.')

  @classmethod
  def is_jar(cls, path):
    """True if the given path represents an existing jar or zip file."""
    return path.endswith(('.jar', '.zip')) and os.path.isfile(path)

  @classmethod
  def is_dir(cls, path):
    """True if the given path represents an existing directory."""
    return os.path.isdir(path)

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
    target_to_classpath = cls.classpath_by_targets(targets, classpath_products)

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
