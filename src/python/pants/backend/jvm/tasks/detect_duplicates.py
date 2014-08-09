# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
from contextlib import closing
import os
from zipfile import ZipFile

from pex.compatibility import to_bytes

from pants.backend.jvm.tasks.jvm_binary_task import JvmBinaryTask
from pants.base.exceptions import TaskError
from pants.java.jar.manifest import Manifest


EXCLUDED_FILES = ("dependencies,license,notice,.DS_Store,notice.txt,cmdline.arg.info.txt.1,"
                  "license.txt")


class DuplicateDetector(JvmBinaryTask):
  """ Detect classes and resources with the same qualified name on the classpath. """

  @staticmethod
  def _isdir(name):
    return name[-1] == '/'

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(DuplicateDetector, cls).setup_parser(option_group, args, mkflag)
    option_group.add_option(mkflag("fail-fast"), mkflag("fail-fast", negate=True),
                            dest="fail_fast", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Fail fast if duplicate classes/resources are found.")
    option_group.add_option(mkflag("excludes"),
                            dest="excludes", default=EXCLUDED_FILES,
                            help="A comma separated list of case insensitive filenames (without "
                                 "directory) to exclude from duplicate check, "
                                 "defaults to: [%default]")
    option_group.add_option(mkflag("max-dups"),
                            dest="max_dups", default=10,
                            help="Maximum number of duplicate classes to display per artifact"
                                 "defaults to: [%default]")

  def __init__(self, *args, **kwargs):
    super(DuplicateDetector, self).__init__(*args, **kwargs)
    self._fail_fast = self.context.options.fail_fast
    excludes = self.context.options.excludes
    if not excludes:
      excludes = EXCLUDED_FILES
    self._excludes = set([x.lower() for x in excludes.split(',')])
    self._max_dups = int(self.context.options.max_dups)

  def prepare(self, round_manager):
    round_manager.require_data('resources_by_target')
    round_manager.require_data('classes_by_target')

  def execute(self):
    for binary_target in filter(self.is_binary, self.context.targets()):
      self.detect_duplicates_for_target(binary_target)

  def detect_duplicates_for_target(self, binary_target):
    artifacts_by_file_name = defaultdict(set)

    # Extract external dependencies on libraries (jars)
    external_deps = self._get_external_dependencies(binary_target)
    for (file_name, targets) in external_deps.items():
      artifacts_by_file_name[file_name].update(targets)

    # Extract internal dependencies on classes and resources
    internal_deps = self._get_internal_dependencies(binary_target)
    for (file_name, targets) in internal_deps.items():
      artifacts_by_file_name[file_name].update(targets)

    self._is_conflicts(artifacts_by_file_name, binary_target)

  def _is_conflicts(self, artifacts_by_file_name, binary_target):
    conflicts_by_artifacts = self._get_conflicts_by_artifacts(artifacts_by_file_name)

    if len(conflicts_by_artifacts) > 0:
      self._log_conflicts(conflicts_by_artifacts, binary_target)
      if self._fail_fast:
        raise TaskError('Failing build for target %s.' % binary_target)
      return True
    return False

  def _get_internal_dependencies(self, binary_target):
    artifacts_by_file_name = defaultdict(set)
    classes_by_target = self.context.products.get_data('classes_by_target')
    resources_by_target = self.context.products.get_data('resources_by_target')

    target_products = classes_by_target.get(binary_target)
    if target_products:  # Will be None if binary_target has no sources.
      for _, classes in target_products.rel_paths():
        for cls in classes:
          artifacts_by_file_name[cls].add(binary_target)

    target_resources = []
    if binary_target.has_resources:
      target_resources.extend(resources_by_target.get(r) for r in binary_target.resources)

    for r in target_resources:
      artifacts_by_file_name[r].add(binary_target)
    return artifacts_by_file_name

  def _get_external_dependencies(self, binary_target):
    artifacts_by_file_name = defaultdict(set)
    for basedir, externaljar in  self.list_external_jar_dependencies(binary_target):
      external_dep = os.path.join(basedir, externaljar)
      self.context.log.debug('  scanning %s' % external_dep)
      with closing(ZipFile(external_dep)) as dep_zip:
        for qualified_file_name in dep_zip.namelist():
          # Zip entry names can come in any encoding and in practice we find some jars that have
          # utf-8 encoded entry names, some not.  As a result we cannot simply decode in all cases
          # and need to do this to_bytes(...).decode('utf-8') dance to stay safe across all entry
          # name flavors and under all supported pythons.
          decoded_file_name = to_bytes(qualified_file_name).decode('utf-8')
          if os.path.basename(decoded_file_name).lower() in self._excludes:
            continue
          jar_name = os.path.basename(external_dep)
          if (not self._isdir(decoded_file_name)) and Manifest.PATH != decoded_file_name:
            artifacts_by_file_name[decoded_file_name].add(jar_name)
    return artifacts_by_file_name

  def _get_conflicts_by_artifacts(self, artifacts_by_file_name):
    conflicts_by_artifacts = defaultdict(set)
    for (file_name, artifacts) in artifacts_by_file_name.items():
      if (not artifacts) or len(artifacts) < 2: continue
      conflicts_by_artifacts[tuple(sorted(artifacts))].add(file_name)
    return conflicts_by_artifacts

  def _log_conflicts(self, conflicts_by_artifacts, target):
    self.context.log.warn('\n ===== For target %s:' % target)
    for artifacts, duplicate_files in conflicts_by_artifacts.items():
      if len(artifacts) < 2: continue
      self.context.log.warn(
        'Duplicate classes and/or resources detected in artifacts: %s' % str(artifacts))
      dup_list = list(duplicate_files)
      for duplicate_file in dup_list[:self._max_dups]:
        self.context.log.warn('     %s' % duplicate_file)
      if len(dup_list) > self._max_dups:
        self.context.log.warn('     ... {remaining} more ...'
                              .format(remaining=(len(dup_list)-self._max_dups)))
