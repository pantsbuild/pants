# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.java.util import safe_classpath
from pants.task.task import Task


class RuntimeClasspathPublisher(Task):
  """Create stable symlinks for runtime classpath entries for JVM targets."""

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--manifest-jar-only', type=bool, default=False,
             removal_version='1.25.0.dev2',
             removal_hint='Use --manifest-jar instead, which respects --internal-classpath-only!',
             help='Only export classpath in a manifest jar.')
    register('--manifest-jar', type=bool, default=False,
             help='Export classpath in a manifest jar instead of symlinks in the dist dir.')
    register('--internal-classpath-only', type=bool, default=True,
             help='Only export the classpath of source targets, not jar_library()s.')

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data('runtime_classpath')

  @property
  def _output_folder(self):
    return self.options_scope.replace('.', os.sep)

  def execute(self):
    basedir = os.path.join(self.get_options().pants_distdir, self._output_folder)
    runtime_classpath = self.context.products.get_data('runtime_classpath')
    targets = self.get_targets()
    if self.get_options().manifest_jar:
      classpath_entries = runtime_classpath.get_internal_classpath_entries_for_targets(targets)
      if not self.get_options().internal_classpath_only:
        classpath_entries.extend(runtime_classpath.get_artifact_classpath_entries_for_targets(targets))
      cp_paths = [entry.path for _conf, entry in classpath_entries]
      self.context.log.debug(f'paths: {cp_paths}, entries: {classpath_entries}')
      # Safely create e.g. dist/export-classpath/manifest.jar
      safe_classpath(cp_paths, basedir, "manifest.jar")
    elif self.get_options().manifest_jar_only:
      classpath = ClasspathUtil.classpath(targets, runtime_classpath)
      # Safely create e.g. dist/export-classpath/manifest.jar
      safe_classpath(classpath, basedir, "manifest.jar")
    else:
      ClasspathProducts.create_canonical_classpath(
        runtime_classpath,
        targets,
        basedir,
        internal_classpath_only=self.get_options().internal_classpath_only,
        save_classpath_file=True)
