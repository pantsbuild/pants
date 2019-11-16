# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.jvm.subsystems.resolve_subsystem import JvmResolveSubsystem
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.testutil.subsystem.util import init_subsystem
from pants.testutil.task_test_base import TaskTestBase
from pants.util.dirutil import safe_file_dump, safe_mkdir, safe_mkdtemp


class JvmTaskTestBase(TaskTestBase):
  """
  :API: public
  """

  def setUp(self):
    """
    :API: public
    """
    super().setUp()
    init_subsystem(JvmResolveSubsystem)
    self.set_options_for_scope('resolver', resolver='ivy')
    if os.path.isfile('/PANTS_GCP_REMOTE'):
      # Use the GCP maven mirrors, so we don't get throttled for DOSing maven central.
      # Note that this recapitulates the logic in pants.remote.ini. Unfortunately we
      # can't access the real options inside tests, and plumbing these through everywhere
      # they're needed is prohibitive. So we repeat the logic here.
      maven_central_mirror_root_url = 'https://maven-central.storage-download.googleapis.com/repos/central/data'
      maven_central_mirror_ivy_bootstrap_jar_url = f'{maven_central_mirror_root_url}/org/apache/ivy/ivy/2.4.0/ivy-2.4.0.jar'
      maven_central_mirror_ivy_settings = 'build-support/ivy/remote.ivysettings.xml'

      self.set_options_for_scope('coursier', repos=[maven_central_mirror_root_url])
      for scope in ['ivy', 'ivy.outdated', 'ivy.outdated.ivy']:
        self.set_options_for_scope(scope,
                                   bootstrap_jar_url=maven_central_mirror_ivy_bootstrap_jar_url,
                                   bootstrap_ivy_settings=maven_central_mirror_ivy_settings,
                                   ivy_settings=maven_central_mirror_ivy_settings)

  def populate_runtime_classpath(self, context, classpath=None):
    """
    Helps actual test cases to populate the 'runtime_classpath' products data mapping
    in the context, which holds the classpath value for targets.

    :API: public

    :param context: The execution context where the products data mapping lives.
    :param classpath: a list of classpath strings. If not specified,
                      [os.path.join(self.buildroot, 'none')] will be used.
    """
    classpath = classpath or []
    runtime_classpath = self.get_runtime_classpath(context)
    runtime_classpath.add_for_targets(context.targets(),
                                      [('default', entry) for entry in classpath])

  def add_to_runtime_classpath(self, context, tgt, files_dict):
    """Creates and adds the given files to the classpath for the given target under a temp path.

    :API: public
    """
    runtime_classpath = self.get_runtime_classpath(context)
    # Create a temporary directory under the target id, then dump all files.
    target_dir = os.path.join(self.test_workdir, tgt.id)
    safe_mkdir(target_dir)
    classpath_dir = safe_mkdtemp(dir=target_dir)
    for rel_path, content in files_dict.items():
      safe_file_dump(os.path.join(classpath_dir, rel_path), content)
    # Add to the classpath.
    runtime_classpath.add_for_target(tgt, [('default', classpath_dir)])

  def get_runtime_classpath(self, context):
    """
    :API: public
    """
    return context.products.get_data('runtime_classpath', init_func=ClasspathProducts.init_func(self.pants_workdir))
