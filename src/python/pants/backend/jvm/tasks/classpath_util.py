# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from twitter.common.collections import OrderedSet


class ClasspathUtil(object):

  @classmethod
  def compute_classpath(cls, targets, classpath_products, extra_classpath_tuples, confs):
    """Returns the list of jar entries for a classpath covering all the passed targets. Filters and
    adds paths from extra_classpath_tuples to the end of the resulting list.

    :param targets: Targets to build a aggregated classpath for
    :param UnionProducts classpath_products: Product containing classpath elements.
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
    :param UnionProducts classpath_products: Product containing classpath elements.
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
  def classpath_entries(cls, targets, classpath_products, confs):
    """Returns the list of jar entries for a classpath covering all the passed targets.

    :param targets: Targets to build a aggregated classpath for
    :param UnionProducts classpath_products: Product containing classpath elements.
    :param confs: The list of confs for use by this classpath
    """
    classpath_tuples = classpath_products.get_for_targets(targets)

    tuples = cls._filter_classpath_by_confs(classpath_tuples, confs)

    return cls._pluck_paths(tuples)

  @classmethod
  def _filter_classpath_by_confs(cls, classpath_tuples, confs):
    def conf_needed(conf):
      return conf in confs if confs is not None else True

    return [(conf, path) for conf, path in classpath_tuples
            if conf_needed(conf)]

  @classmethod
  def _pluck_paths(cls, classpath):
    return [path for conf, path in classpath]
