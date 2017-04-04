# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

from pants.backend.jvm.subsystems.shader import Shader
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.java.jar.jar_dependency import JarDependency
from pants.option.custom_types import file_option
from pants.util.dirutil import safe_mkdir
from pants.util.memo import memoized_property
from pants.util.xml_parser import XmlParser
from twitter.common.collections import OrderedSet


class FindBugs(NailgunTask):
  """Check Java code for findbugs violations."""

  _FINDBUGS_MAIN = 'edu.umd.cs.findbugs.FindBugs2'
  _HIGH_PRIORITY_LOWEST_RANK = 4
  _NORMAL_PRIORITY_LOWEST_RANK = 9

  @classmethod
  def register_options(cls, register):
    super(FindBugs, cls).register_options(register)

    register('--skip', type=bool, help='Skip findbugs.')
    register('--transitive', default=False, type=bool,
             help='Run findbugs against transitive dependencies of targets specified on '
                  'the command line.')
    register('--effort', default='default', fingerprint=True,
             choices=['min', 'less', 'default', 'more', 'max'],
             help='Effort of the bug finders.')
    register('--threshold', default='medium', fingerprint=True,
             choices=['low', 'medium', 'high', 'experimental'],
             help='Effort of the bug finders.')
    register('--fail-on-error', type=bool, fingerprint=True,
             help='Fail the build on an error.')
    register('--max-rank', type=int, fingerprint=True,
             help='Maximum bug ranking to record [1..20].')
    register('--relaxed', type=bool, fingerprint=True,
             help='Relaxed reporting mode')
    register('--nested', type=bool, default=True, fingerprint=True,
             help='Analyze nested jar/zip archives')
    register('--exclude-filter-file', type=file_option, fingerprint=True,
             help='Exclude bugs matching given filter')
    register('--include-filter-file', type=file_option, fingerprint=True,
             help='Include only bugs matching given filter')
    register('--exclude-patterns', type=list, default=[], fingerprint=True,
             help='Patterns for targets to be excluded from analysis.')

    cls.register_jvm_tool(register,
                          'findbugs',
                          classpath=[
                            JarDependency(org='com.google.code.findbugs',
                                          name='findbugs',
                                          rev='3.0.1'),
                          ],
                          main=cls._FINDBUGS_MAIN,
                          custom_rules=[
                            Shader.exclude_package('edu.umd.cs.findbugs', recursive=True),
                          ])

  @classmethod
  def prepare(cls, options, round_manager):
    super(FindBugs, cls).prepare(options, round_manager)
    round_manager.require_data('runtime_classpath')

  @property
  def cache_target_dirs(self):
    return True

  @memoized_property
  def _exclude_patterns(self):
    return [re.compile(x) for x in set(self.get_options().exclude_patterns or [])]

  def _is_findbugs_target(self, target):
    if not isinstance(target, (JavaLibrary, JUnitTests)):
      self.context.log.debug('Skipping [{}] because it is not a java library or java test'.format(target.address.spec))
      return False
    if target.is_synthetic:
      self.context.log.debug('Skipping [{}] because it is a synthetic target'.format(target.address.spec))
      return False
    for pattern in self._exclude_patterns:
      if pattern.search(target.address.spec):
        self.context.log.debug(
          "Skipping [{}] because it matches exclude pattern '{}'".format(target.address.spec, pattern.pattern))
        return False
    return True

  def execute(self):
    if self.get_options().skip:
      return

    if self.get_options().transitive:
      targets = self.context.targets(self._is_findbugs_target)
    else:
      targets = filter(self._is_findbugs_target, self.context.target_roots)

    bug_counts = { 'error': 0, 'high': 0, 'normal': 0, 'low': 0 }
    target_count = 0
    with self.invalidated(targets, invalidate_dependents=True) as invalidation_check:
      total_targets = len(invalidation_check.invalid_vts)
      for vt in invalidation_check.invalid_vts:
        target_count += 1
        self.context.log.info('[{}/{}] {}'.format(
          str(target_count).rjust(len(str(total_targets))),
          total_targets,
          vt.target.address.spec))

        target_bug_counts = self.findbugs(vt.target)
        if not self.get_options().fail_on_error or sum(target_bug_counts.values()) == 0:
          vt.update()
        bug_counts = {k: bug_counts.get(k, 0) + target_bug_counts.get(k, 0) for k in bug_counts.keys()}

      error_count = bug_counts.pop('error', 0)
      bug_counts['total'] = sum(bug_counts.values())
      if error_count + bug_counts['total'] > 0:
        self.context.log.info('')
        if error_count > 0:
          self.context.log.warn('Errors: {}'.format(error_count))
        if bug_counts['total'] > 0:
          self.context.log.warn("Bugs: {total} (High: {high}, Normal: {normal}, Low: {low})".format(**bug_counts))
        if self.get_options().fail_on_error:
          raise TaskError('failed with {bug} bugs and {err} errors'.format(
            bug=bug_counts['total'], err=error_count))

  def findbugs(self, target):
    runtime_classpaths = self.context.products.get_data('runtime_classpath')
    runtime_classpath = runtime_classpaths.get_for_targets(target.closure(bfs=True))
    aux_classpath = OrderedSet(jar for conf, jar in runtime_classpath if conf == 'default')

    target_jars = OrderedSet(jar for conf, jar in runtime_classpaths.get_for_target(target) if conf == 'default')

    bug_counts = { 'error': 0, 'high': 0, 'normal': 0, 'low': 0 }

    if not target_jars:
      self.context.log.info('  No jars to be analyzed')
      return bug_counts

    output_dir = os.path.join(self.workdir, target.id)
    safe_mkdir(output_dir)
    output_file = os.path.join(output_dir, 'findbugsXml.xml')

    args = [
      '-auxclasspath', ':'.join(aux_classpath - target_jars),
      '-projectName', target.address.spec,
      '-xml:withMessages',
      '-effort:{}'.format(self.get_options().effort),
      '-{}'.format(self.get_options().threshold),
      '-nested:{}'.format('true' if self.get_options().nested else 'false'),
      '-output', output_file,
      '-noClassOk'
    ]

    if self.get_options().exclude_filter_file:
      args.extend(['-exclude', os.path.join(get_buildroot(), self.get_options().exclude_filter_file)])

    if self.get_options().include_filter_file:
      args.extend(['-include', os.path.join(get_buildroot(), self.get_options().include_filter_file)])

    if self.get_options().max_rank:
      args.extend(['-maxRank', str(self.get_options().max_rank)])

    if self.get_options().relaxed:
      args.extend(['-relaxed'])

    if self.get_options().level == 'debug':
      args.extend(['-progress'])

    args.extend(target_jars)
    result = self.runjava(classpath=self.tool_classpath('findbugs'),
                          main=self._FINDBUGS_MAIN,
                          jvm_options=self.get_options().jvm_options,
                          args=args,
                          workunit_name='findbugs',
                          workunit_labels=[WorkUnitLabel.LINT])
    if result != 0:
      raise TaskError('java {main} ... exited non-zero ({result})'.format(
          main=self._FINDBUGS_MAIN, result=result))

    xml = XmlParser.from_file(output_file)
    for error in xml.parsed.getElementsByTagName('Error'):
      self.context.log.warn('Error: {msg}'.format(
        msg=error.getElementsByTagName('ErrorMessage')[0].firstChild.data))
      bug_counts['error'] += 1

    for bug_instance in xml.parsed.getElementsByTagName('BugInstance'):
      bug_rank = bug_instance.getAttribute('rank')
      if int(bug_rank) <= self._HIGH_PRIORITY_LOWEST_RANK:
        priority = 'high'
      elif int(bug_rank) <= self._NORMAL_PRIORITY_LOWEST_RANK:
        priority = 'normal'
      else:
        priority = 'low'
      bug_counts[priority] += 1

      source_line = bug_instance.getElementsByTagName('Class')[0].getElementsByTagName('SourceLine')[0]
      self.context.log.warn('Bug[{priority}]: {type} {desc} {line}'.format(
        priority=priority,
        type=bug_instance.getAttribute('type'),
        desc=bug_instance.getElementsByTagName('LongMessage')[0].firstChild.data,
        line=source_line.getElementsByTagName('Message')[0].firstChild.data))

    return bug_counts
