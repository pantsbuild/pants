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
  def compute_classpath(targets, extra_classpath_tuples, products, confs):
    """Returns the list of jar entries for a classpath covering all the passed targets.

    :param targets: Targets to build a aggregated classpath for
    :param extra_classpath_tuples: Additional (conf, path) pairs to be added to the classpath
    :param products: The products manager for the current run
    :param confs: The list of confs for use by this classpath
    """
    extra_classpath_paths = ClasspathUtil._just_paths(extra_classpath_tuples)

    compile_classpaths = products.get_data('compile_classpath')
    all_targets_compile_classpath = ClasspathUtil.classpath_entries(targets, compile_classpaths,
                                                                    confs)
    compile_classpath = OrderedSet(list(all_targets_compile_classpath) +
                                   extra_classpath_paths)
    return list(compile_classpath)

  @staticmethod
  def compute_classpath_for_target(compile_classpaths, target, extra_classpath_tuples,
                          target_closure,
                          confs):
    """Returns the list of jar entries for a classpath covering the passed target.

    :param UnionProduct compile_classpaths: Product containing classpath elements.
    :param target: The target to generate a classpath for
    :param extra_classpath_tuples: Additional classpath entries
    :param target_closure: The transitive closure of the target
    :param confs: The list of confs for use by this classpath
    """
    classpath_for_target = ClasspathUtil.classpath_entries_for_target(target,
                                                                      compile_classpaths,
                                                                      confs=confs,
                                                                      target_closure=target_closure)

    extra_compiletime_classpath_paths = ClasspathUtil. \
      _filter_classpath_and_include_only_paths(extra_classpath_tuples, [], confs)
    ClasspathUtil._validate_classpath_paths(extra_classpath_tuples)

    compile_classpath = classpath_for_target + \
                        extra_compiletime_classpath_paths
    return list(compile_classpath)

  @staticmethod
  def classpath_entries_for_target(target, compile_classpaths, confs, target_closure=None):
    compile_classpath = compile_classpaths.get_for_target(target)
    exclude_patterns = ClasspathUtil._exclude_patterns_for_closure(target_closure or target.closure())

    paths = ClasspathUtil._filter_classpath_and_include_only_paths(compile_classpath,
                                                                   exclude_patterns, confs)
    ClasspathUtil._validate_classpath_paths(paths)
    return paths

  @staticmethod
  def classpath_entries(targets, compile_classpaths, confs):
    compile_classpath = compile_classpaths.get_for_targets(targets)
    exclude_patterns = ClasspathUtil._exclude_patterns(targets)
    paths = ClasspathUtil._filter_classpath_and_include_only_paths(compile_classpath,
                                                                   exclude_patterns, confs)
    ClasspathUtil._validate_classpath_paths(paths)
    return paths

  @staticmethod
  def _filter_classpath_and_include_only_paths(compile_classpath, exclude_patterns, confs):
    def conf_needed(conf):
      return not confs or conf in confs

    def excluded(path):
      return any(excluded in path for excluded in exclude_patterns)

    return [path for conf, path in compile_classpath
            if conf_needed(conf) and not excluded(path)]

  @staticmethod
  def _filter_classpath(compile_classpath, exclude_patterns, confs):
    def conf_needed(conf):
      return not confs or conf in confs

    def excluded(path):
      return any(excluded in path for excluded in exclude_patterns)

    return [(conf, path) for conf, path in compile_classpath
            if conf_needed(conf) and not excluded(path)]

  @staticmethod
  def _just_paths(classpath):
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
