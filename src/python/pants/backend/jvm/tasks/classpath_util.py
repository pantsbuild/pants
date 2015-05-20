# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from twitter.common.collections import OrderedSet

from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError


class ClasspathUtil(object):

  @staticmethod
  def compute_classpath(targets, extra_classpath_tuples, classpath_products, confs):
    """Returns the list of jar entries for a classpath covering all the passed targets. Filters and
    adds paths from extra_classpath_tuples to the end of the resulting list.

    :param targets: Targets to build a aggregated classpath for
    :param extra_classpath_tuples: Additional (conf, path) pairs to be added to the classpath
    :param UnionProducts classpath_products: Product containing classpath elements.
    :param confs: The list of confs for use by this classpath
    """
    extra_classpath_paths = ClasspathUtil._pluck_paths(extra_classpath_tuples)

    all_targets_compile_classpath = ClasspathUtil.classpath_entries(targets, classpath_products,
                                                                    confs)
    compile_classpath = OrderedSet(list(all_targets_compile_classpath) +
                                   extra_classpath_paths)
    return list(compile_classpath)

  @staticmethod
  def compute_classpath_for_target(target, classpath_products, extra_classpath_tuples, confs,
                                   target_closure=None):
    """Returns the list of jar entries for a classpath covering the passed target. Filters and adds
    paths from extra_classpath_tuples to the end of the resulting list.

    :param UnionProducts classpath_products: Product containing classpath elements.
    :param target: The target to generate a classpath for
    :param extra_classpath_tuples: Additional classpath entries
    :param target_closure: The transitive closure of the target
    :param confs: The list of confs for use by this classpath
    """
    classpath_for_target = ClasspathUtil.classpath_entries_for_target(target,
                                                                      classpath_products,
                                                                      confs=confs,
                                                                      target_closure=target_closure)

    filtered_extra_classpath_tuples = ClasspathUtil. \
      _filter_classpath_by_excludes_and_confs(extra_classpath_tuples, [], confs)
    extra_classpath_paths = ClasspathUtil._pluck_paths(filtered_extra_classpath_tuples)
    ClasspathUtil._validate_classpath_paths(filtered_extra_classpath_tuples)

    compile_classpath = classpath_for_target + extra_classpath_paths
    return list(compile_classpath)

  @staticmethod
  def classpath_entries_for_target(target, classpath_products, confs, target_closure=None):
    compile_classpath = classpath_products.get_for_target(target)
    target_closure = target_closure or target.closure()
    exclude_patterns = ClasspathUtil._exclude_patterns_for_closure(target_closure)

    tuples = ClasspathUtil._filter_classpath_by_excludes_and_confs(compile_classpath,
                                                                   exclude_patterns, confs)
    paths = ClasspathUtil._pluck_paths(tuples)
    ClasspathUtil._validate_classpath_paths(paths)
    return paths

  @staticmethod
  def classpath_entries(targets, classpath_products, confs):
    compile_classpath = classpath_products.get_for_targets(targets)
    exclude_patterns = ClasspathUtil._exclude_patterns(targets)
    tuples = ClasspathUtil._filter_classpath_by_excludes_and_confs(compile_classpath,
                                                                   exclude_patterns, confs)
    paths = ClasspathUtil._pluck_paths(tuples)
    ClasspathUtil._validate_classpath_paths(paths)
    return paths

  @staticmethod
  def _filter_classpath_by_excludes_and_confs(compile_classpath, exclude_patterns, confs):
    def conf_needed(conf):
      return conf in confs if confs else True

    def excluded(path):
      return any(excluded in path for excluded in exclude_patterns)

    return [(conf, path) for conf, path in compile_classpath
            if conf_needed(conf) and not excluded(path)]

  @staticmethod
  def _pluck_paths(classpath):
    return [path for conf, path in classpath]

  @staticmethod
  def _exclude_patterns(targets):
    patterns = set()
    for target in targets:
      patterns.update(ClasspathUtil._exclude_patterns_for_closure(target.closure()))
    return patterns

  @staticmethod
  def _exclude_patterns_for_closure(target_closure):
    # creates strings from excludes that will match classpath entries generated by ivy
    # eg exclude(org='org.example', name='lib') => 'jars/org.example/lib'
    #    exclude(org='org.example')             => 'jars/org.example/'
    excludes_patterns = set()
    for target in target_closure:
      if isinstance(target, (JvmTarget, JarLibrary)) and target.excludes:
        excludes_patterns.update([os.path.sep.join(['jars', e.org, e.name or ''])
                                  for e in target.excludes])
    return excludes_patterns

  @staticmethod
  def _validate_classpath_paths(classpath):
    """Validates that all files are located within the working copy, to simplify relativization."""
    buildroot = get_buildroot()
    for f in classpath:
      if os.path.relpath(f, buildroot).startswith('..'):
        raise TaskError('Classpath entry {} is located outside the buildroot.'.format(f))
