# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from twitter.common.collections import OrderedSet

from pants.util.contextutil import open_zip
from pants.util.dirutil import fast_relpath, safe_walk


class ClasspathUtil(object):

  @classmethod
  def compute_classpath(cls, targets, classpath_products, extra_classpath_tuples, confs):
    """Returns the list of jar entries for a classpath covering all the passed targets. Filters and
    adds paths from extra_classpath_tuples to the end of the resulting list.

    :param targets: Targets to build a aggregated classpath for
    :param ClasspathProducts classpath_products: Product containing classpath elements.
    :param extra_classpath_tuples: Additional (conf, path) pairs to be added to the classpath
    :param confs: The list of confs for use by this classpath
    """

    all_targets_classpath_entries = cls.classpath_entries(targets, classpath_products, confs)

    extra_classpath_paths = cls._pluck_paths(extra_classpath_tuples)
    classpath_paths = OrderedSet(list(all_targets_classpath_entries) + extra_classpath_paths)
    return list(classpath_paths)

  @classmethod
  def compute_classpath_for_target(cls, target, classpath_products, extra_classpath_tuples, confs,
                                   target_closure=None):
    """Returns the list of jar entries for a classpath covering the passed target. Filters and adds
    paths from extra_classpath_tuples to the end of the resulting list.

    :param target: The target to generate a classpath for
    :param ClasspathProducts classpath_products: Product containing classpath elements.
    :param extra_classpath_tuples: Additional classpath entries
    :param confs: The list of confs for use by this classpath
    :param target_closure: The transitive closure of the target
    """

    classpath_tuples = classpath_products.get_for_target(target)

    filtered_classpath_tuples = cls._filter_classpath_by_confs(classpath_tuples, confs)

    filtered_extra_classpath_tuples = cls._filter_classpath_by_confs(extra_classpath_tuples, confs)

    full_classpath_tuples = filtered_classpath_tuples + filtered_extra_classpath_tuples

    return cls._pluck_paths(full_classpath_tuples)

  @classmethod
  def classpath_entries(cls, targets, classpath_products, confs, transitive=True, jars_only=False):
    """Returns the list of entries for a classpath covering all the passed targets.

    :param targets: Targets to build a aggregated classpath for
    :param ClasspathProducts classpath_products: Product containing classpath elements.
    :param confs: The list of confs for use by this classpath
    """
    classpath_tuples = classpath_products.get_for_targets(targets, transitive=transitive)

    tuples = cls._filter_classpath_by_confs(classpath_tuples, confs)

    return cls._pluck_paths(tuples, jars_only=jars_only)

  @classmethod
  def _filter_classpath_by_confs(cls, classpath_tuples, confs):
    accept = (lambda conf: conf in confs) if (confs is not None) else (lambda _: True)
    return [(conf, path) for conf, path in classpath_tuples if accept(conf)]

  @classmethod
  def _pluck_paths(cls, classpath, jars_only=False):
    accept = (lambda p: cls.is_jar(p)) if jars_only else (lambda _: True)
    return [path for conf, path in classpath if accept(path)]

  @classmethod
  def classpath_contents(cls, targets, classpath_products, confs, transitive=True):
    """Provides a generator over the contents (classes/resources) of a classpath.

    No particular order is guaranteed (TODO: yet?).
    """
    for entry in cls.classpath_entries(targets, classpath_products, confs, transitive=transitive):
      if cls.is_jar(entry):
        with open_zip(entry, mode='r') as jar:
          for name in jar.namelist():
            yield name
      elif os.path.isdir(entry):
        for abs_sub_dir, dirnames, filenames in safe_walk(entry):
          def rel_walk_name(name):
            return fast_relpath(os.path.join(abs_sub_dir, name), entry)
          for name in dirnames:
            yield '{}/'.format(rel_walk_name(name))
          for name in filenames:
            yield rel_walk_name(name)
      else:
        # non-jar and non-directory classpath entries should be ignored
        pass

  @classmethod
  def classname_for_rel_classfile(cls, class_file_name):
    """Return the class name for the given relative-to-a-classpath-entry file, or None."""
    if not class_file_name.endswith(".class"):
      return None
    return class_file_name[:-len(".class")].replace("/", ".")

  @classmethod
  def is_jar(cls, path):
    """True if the given path represents an existing jar file."""
    return path.endswith('.jar') and os.path.isfile(path)
