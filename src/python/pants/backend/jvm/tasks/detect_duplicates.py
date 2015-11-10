# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from pex.compatibility import to_bytes

from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.backend.jvm.tasks.jvm_binary_task import JvmBinaryTask
from pants.base.exceptions import TaskError
from pants.java.jar.manifest import Manifest
from pants.util.contextutil import open_zip


EXCLUDED_FILES = ['dependencies,license,notice,.DS_Store,notice.txt,cmdline.arg.info.txt.1,'
                  'license.txt']


class DuplicateDetector(JvmBinaryTask):
  """ Detect classes and resources with the same qualified name on the classpath. """

  @staticmethod
  def _isdir(name):
    return name[-1] == '/'

  @classmethod
  def register_options(cls, register):
    super(DuplicateDetector, cls).register_options(register)
    register('--excludes', default=EXCLUDED_FILES, action='append',
             help='Case insensitive filenames (without directory) to exclude from duplicate check. '
                  'Filenames can be specified in a comma-separated list or by using multiple '
                  'instances of this flag.')
    register('--max-dups', type=int, default=10,
             help='Maximum number of duplicate classes to display per artifact.')

  @classmethod
  def prepare(cls, options, round_manager):
    super(DuplicateDetector, cls).prepare(options, round_manager)
    round_manager.require_data('runtime_classpath')

  def __init__(self, *args, **kwargs):
    super(DuplicateDetector, self).__init__(*args, **kwargs)
    self._fail_fast = self.get_options().fail_fast
    excludes = self.get_options().excludes
    self._excludes = set([x.lower() for exclude in excludes for x in exclude.split(',')])
    self._max_dups = int(self.get_options().max_dups)

  def execute(self):
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
      if self._fail_fast:
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
        if not f.endswith('/'):
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
          if os.path.basename(decoded_file_name).lower() in self._excludes:
            continue
          if (not self._isdir(decoded_file_name)) and Manifest.PATH != decoded_file_name:
            artifacts_by_file_name[decoded_file_name].add(coordinate.artifact_filename)
    return artifacts_by_file_name

  def _get_conflicts_by_artifacts(self, artifacts_by_file_name):
    conflicts_by_artifacts = defaultdict(set)
    for (file_name, artifacts) in artifacts_by_file_name.items():
      if (not artifacts) or len(artifacts) < 2:
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
      for duplicate_file in dup_list[:self._max_dups]:
        self.context.log.warn('     {}'.format(duplicate_file))
      if len(dup_list) > self._max_dups:
        self.context.log.warn('     ... {remaining} more ...'
                              .format(remaining=(len(dup_list) - self._max_dups)))
