# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

from twitter.common.collections import OrderedSet

from pants.util.contextutil import open_zip
from pants.util.dirutil import fast_relpath, safe_delete, safe_open, safe_walk


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
  def _filtered_classpath_by_confs_iter(cls, classpath_tuples, confs):
    accept = (lambda conf: conf in confs) if (confs is not None) else (lambda _: True)
    for conf, entry in classpath_tuples:
      if accept(conf):
        yield conf, entry

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
                                 use_target_id=True):
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
    :param use_target_id: Optionally switch to the subdirectory based symlinks naming.
      This is added for backward compatibility. Remove once intellij plugin is ready to use
      `target.id` based output files.  See `use_old_naming_style` option in :class:
      `pants.backend.jvm.tasks.jvm_compile.jvm_classpath_publisher.RuntimeClasspathPublisher`.

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
      if use_target_id:
        output_dir = basedir
        # TODO(peiyu) improve readability once we deprecate the old naming style.
        # For example, `-` is commonly placed in string format as opposed to here.
        classpath_prefix_for_target = '{basedir}/{target_id}-'.format(basedir=basedir,
                                                                      target_id=target.id)
      else:
        address = target.address
        output_dir = os.path.join(
          basedir,
          # target.address.spec is used in export goal to identify targets
          address.spec.replace(':', os.sep) if address.spec_path else address.target_name,
        )
        # append / to the end as part of the prefix
        classpath_prefix_for_target = os.path.join(output_dir, '')

      if os.path.exists(output_dir):
        delete_old_target_output_files(classpath_prefix_for_target)
      else:
        os.makedirs(output_dir)
      return classpath_prefix_for_target

    canonical_classpath = []
    for target in targets:
      classpath_prefix_for_target = prepare_target_output_folder(basedir, target)

      classpath_entries_for_target = classpath_products.get_internal_classpath_entries_for_targets(
        [target])

      if len(classpath_entries_for_target) > 0:

        classpath = []
        for (index, (conf, entry)) in enumerate(classpath_entries_for_target):
          classpath.append(entry.path)
          # Create a unique symlink path by prefixing the base file name with a monotonic
          # increasing `index` to avoid name collisions.
          _, ext = os.path.splitext(entry.path)

          symlink_path = '{}{}{}'.format(classpath_prefix_for_target, index, ext)
          os.symlink(entry.path, symlink_path)
          canonical_classpath.append(symlink_path)

        if save_classpath_file:
          with safe_open('{}classpath.txt'.format(classpath_prefix_for_target), 'wb') as classpath_file:
            classpath_file.write(os.pathsep.join(classpath).encode('utf-8'))
            classpath_file.write('\n')

    return canonical_classpath
