# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from collections import defaultdict
from contextlib import closing
from zipfile import ZipFile

from pants.java.jar import Manifest
from pants.tasks import TaskError
from pants.tasks.jvm_binary_task import JvmBinaryTask


class DuplicateDetector(JvmBinaryTask):
  """ Detect classes and resources with the same qualified name on the classpath. """

  @staticmethod
  def _isdir(name):
    return name[-1] == '/'

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    JvmBinaryTask.setup_parser(option_group, args, mkflag)
    option_group.add_option(mkflag("fail-fast"), mkflag("fail-fast", negate=True),
                            dest="fail_fast", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Fail fast if duplicate classes/resources are found.")

  def __init__(self, context):
    JvmBinaryTask.__init__(self, context)
    self.require_jar_dependencies()
    self.fail_fast = context.options.fail_fast

  def execute(self, targets):
    for binary in filter(self.is_binary, targets):
      self.detect_duplicates_for_target(binary)

  def detect_duplicates_for_target(self, binary_target):
    list_path = []
    for basedir, externaljar in self.list_jar_dependencies(binary_target):
      list_path.append(os.path.join(basedir, externaljar))
    self._is_conflicts(list_path, binary_target)

  def _is_conflicts(self, jar_paths, binary_target):
    artifacts_by_file_name = defaultdict(set)
    for jarpath in jar_paths:
      self.context.log.debug('  scanning %s' % jarpath)
      with closing(ZipFile(jarpath)) as zip:
        for file_name in zip.namelist():
          jar_name = os.path.basename(jarpath)
          if (not self._isdir(file_name)) and Manifest.PATH != file_name:
            artifacts_by_file_name[file_name].add(jar_name)
        zip.close()

    conflicts_by_artifacts = self._get_conflicts_by_artifacts(artifacts_by_file_name)

    if len(conflicts_by_artifacts) > 0:
      self._log_conflicts(conflicts_by_artifacts, binary_target)
      if self.fail_fast:
        raise TaskError('Failing build for target %s.' % binary_target)
      return True
    return False

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
      for duplicate_file in list(duplicate_files)[:10]:
        self.context.log.warn('     %s' % duplicate_file)
