# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
from collections import defaultdict

from pex.compatibility import to_bytes

from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.backend.jvm.tasks.jvm_binary_task import JvmBinaryTask
from pants.base.exceptions import TaskError
from pants.java.jar.manifest import Manifest
from pants.util.contextutil import open_zip
from pants.util.memo import memoized_property


EXCLUDED_FILES = ['.DS_Store', 'cmdline.arg.info.txt.1', 'dependencies',
                  'license', 'license.txt', 'notice','notice.txt']
EXCLUDED_DIRS = ['META-INF/services']
EXCLUDED_PATTERNS=[r'^META-INF/[^/]+\.(SF|DSA|RSA)$']  # signature file


class DuplicateDetector(JvmBinaryTask):
  """ Detect JVM classes and resources with the same qualified name on the classpath. """

  @staticmethod
  def _isdir(name):
    return name[-1] == '/'

  @classmethod
  def register_options(cls, register):
    super(DuplicateDetector, cls).register_options(register)
    register('--exclude-files', default=EXCLUDED_FILES, type=list,
             help='Case insensitive filenames (without directory) to exclude from duplicate check.')
    register('--exclude-dirs', default=EXCLUDED_DIRS, type=list,
             help='Directory names to exclude from duplicate check.')
    register('--exclude-patterns', default=EXCLUDED_PATTERNS, type=list,
             help='Regular expressions matching paths (directory and filename) to exclude from '
                  'the duplicate check.')
    register('--max-dups', type=int, default=10,
             help='Maximum number of duplicate classes to display per artifact.')
    register('--skip', type=bool,
             help='Disable the dup checking step.')

  @classmethod
  def prepare(cls, options, round_manager):
    super(DuplicateDetector, cls).prepare(options, round_manager)
    round_manager.require_data('runtime_classpath')

  @memoized_property
  def max_dups(self):
    return int(self.get_options().max_dups)

  @memoized_property
  def exclude_files(self):
    return set([x.lower() for x in self.get_options().exclude_files] or [])

  @memoized_property
  def exclude_dirs(self):
    return set(self.get_options().exclude_dirs)

  @memoized_property
  def exclude_patterns(self):
    return [re.compile(x) for x in set(self.get_options().exclude_patterns or [])]

  def execute(self):
    if self.get_options().skip:
      self.context.log.debug("Duplicate checking is disabled.")
      return None

    conflicts_by_binary = {}
    for binary_target in filter(self.is_binary, self.context.targets()):
      conflicts_by_artifacts = self.detect_duplicates_for_target(binary_target)
      if conflicts_by_artifacts:
        conflicts_by_binary[binary_target] = conflicts_by_artifacts

    # Conflict structure returned for tests.
    return conflicts_by_binary

  def detect_duplicates_for_target(self, binary_target):
    artifacts_by_file_name = defaultdict(set)

    # Extract external dependencies on libraries (jars)
    external_deps = self._get_external_dependencies(binary_target)
    for (file_name, jar_names) in external_deps.items():
      artifacts_by_file_name[file_name].update(jar_names)

    # Extract internal dependencies on classes and resources
    internal_deps = self._get_internal_dependencies(binary_target)
    for (file_name, target_specs) in internal_deps.items():
      artifacts_by_file_name[file_name].update(target_specs)

    return self._check_conflicts(artifacts_by_file_name, binary_target)

  def _check_conflicts(self, artifacts_by_file_name, binary_target):
    conflicts_by_artifacts = self._get_conflicts_by_artifacts(artifacts_by_file_name)
    if len(conflicts_by_artifacts) > 0:
      self._log_conflicts(conflicts_by_artifacts, binary_target)
      if self.get_options().fail_fast:
        raise TaskError('Failing build for target {}.'.format(binary_target))
    return conflicts_by_artifacts

  def _get_internal_dependencies(self, binary_target):
    artifacts_by_file_name = defaultdict(set)
    classpath_products = self.context.products.get_data('runtime_classpath')

    # Select classfiles from the classpath - we want all the direct products of internal targets,
    # no external JarLibrary products.
    def record_file_ownership(target):
      entries = ClasspathUtil.internal_classpath([target], classpath_products)
      for f in ClasspathUtil.classpath_entries_contents(entries):
        artifacts_by_file_name[f].add(target.address.reference())

    binary_target.walk(record_file_ownership)
    return artifacts_by_file_name

  def _get_external_dependencies(self, binary_target):
    artifacts_by_file_name = defaultdict(set)
    for external_dep, coordinate in self.list_external_jar_dependencies(binary_target):
      self.context.log.debug('  scanning {} from {}'.format(coordinate, external_dep))
      with open_zip(external_dep) as dep_zip:
        for qualified_file_name in dep_zip.namelist():
          # Zip entry names can come in any encoding and in practice we find some jars that have
          # utf-8 encoded entry names, some not.  As a result we cannot simply decode in all cases
          # and need to do this to_bytes(...).decode('utf-8') dance to stay safe across all entry
          # name flavors and under all supported pythons.
          decoded_file_name = to_bytes(qualified_file_name).decode('utf-8')
          artifacts_by_file_name[decoded_file_name].add(coordinate.artifact_filename)
    return artifacts_by_file_name

  def _is_excluded(self, path):
    if self._isdir(path) or Manifest.PATH == path:
      return True
    if os.path.basename(path).lower() in self.exclude_files:
      return True
    if os.path.dirname(path) in self.exclude_dirs:
      return True
    for pattern in self.exclude_patterns:
      if pattern.search(path):
        return True
    return False

  def _get_conflicts_by_artifacts(self, artifacts_by_file_name):
    conflicts_by_artifacts = defaultdict(set)
    for (file_name, artifacts) in artifacts_by_file_name.items():
      if (not artifacts) or len(artifacts) < 2:
        continue
      if self._is_excluded(file_name):
        continue
      conflicts_by_artifacts[tuple(sorted(str(a) for a in artifacts))].add(file_name)
    return conflicts_by_artifacts

  def _log_conflicts(self, conflicts_by_artifacts, target):
    self.context.log.warn('\n ===== For target {}:'.format(target))
    for artifacts, duplicate_files in conflicts_by_artifacts.items():
      if len(artifacts) < 2:
        continue
      self.context.log.warn(
        'Duplicate classes and/or resources detected in artifacts: {}'.format(artifacts))
      dup_list = list(duplicate_files)
      for duplicate_file in dup_list[:self.max_dups]:
        self.context.log.warn('     {}'.format(duplicate_file))
      if len(dup_list) > self.max_dups:
        self.context.log.warn('     ... {remaining} more ...'
                              .format(remaining=(len(dup_list) - self.max_dups)))
