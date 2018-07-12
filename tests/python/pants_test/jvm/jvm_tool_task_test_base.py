# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import shutil

from pants.backend.jvm.register import build_file_aliases
from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.backend.jvm.tasks.bootstrap_jvm_tools import BootstrapJvmTools
from pants.base.build_environment import get_pants_cachedir
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.target import Target
from pants.ivy.bootstrapper import Bootstrapper
from pants.util.dirutil import safe_mkdir
from pants_test.jvm.jvm_task_test_base import JvmTaskTestBase


class JvmToolTaskTestBase(JvmTaskTestBase):
  """Prepares an ephemeral test build root that supports tasks that use jvm tool bootstrapping.

  :API: public
  """

  @classmethod
  def alias_groups(cls):
    """
    :API: public
    """
    # Aliases appearing in our real BUILD.tools.
    return build_file_aliases().merge(BuildFileAliases(targets={'target': Target}))

  def setUp(self):
    """
    :API: public
    """
    super(JvmToolTaskTestBase, self).setUp()

    # Use a synthetic subclass for proper isolation when bootstrapping within the test.
    bootstrap_scope = 'bootstrap_scope'
    self.bootstrap_task_type = self.synthesize_task_subtype(BootstrapJvmTools, bootstrap_scope)
    JvmToolMixin.reset_registered_tools()

    # Set some options:

    # 1. Cap BootstrapJvmTools memory usage in tests.  The Xmx was empirically arrived upon using
    #    -Xloggc and verifying no full gcs for a test using the full gamut of resolving a multi-jar
    #    tool, constructing a fat jar and then shading that fat jar.
    #
    # 2. Allow tests to read/write tool jars from the real artifact cache, so they don't
    #    each have to resolve and shade them every single time, which is a huge slowdown.
    #    Note that local artifact cache writes are atomic, so it's fine for multiple concurrent
    #    tests to write to it.
    #
    # Note that we don't have access to the invoking pants instance's options, so we assume that
    # its artifact cache is in the standard location.  If it isn't, worst case the tests will
    # populate a second cache at the standard location, which is no big deal.
    # TODO: We really need a straightforward way for pants's own tests to get to the enclosing
    # pants instance's options values.
    artifact_caches = [os.path.join(get_pants_cachedir(), 'artifact_cache')]
    self.set_options_for_scope(bootstrap_scope, jvm_options=['-Xmx128m'])
    self.set_options_for_scope('cache.{}'.format(bootstrap_scope),
                               read_from=artifact_caches,
                               write_to=artifact_caches)

    # Tool option defaults currently point to targets in the real BUILD.tools, so we copy it and
    # its dependency BUILD files into our test workspace.
    shutil.copy(os.path.join(self.real_build_root, 'BUILD.tools'), self.build_root)
    third_party = os.path.join(self.build_root, '3rdparty')
    safe_mkdir(third_party)
    shutil.copy(os.path.join(self.real_build_root, '3rdparty', 'BUILD'), third_party)

    Bootstrapper.reset_instance()

  def context(self, for_task_types=None, **kwargs):
    """
    :API: public
    """
    # Add in the bootstrapper task type, so its options get registered and set.
    for_task_types = [self.bootstrap_task_type] + (for_task_types or [])
    return super(JvmToolTaskTestBase, self).context(for_task_types=for_task_types, **kwargs)

  def prepare_execute(self, context):
    """Prepares a jvm tool-using task for execution, first bootstrapping any required jvm tools.

    Note: Other task pre-requisites will not be ensured and tests must instead setup their own
          product requirements if any.

    :API: public

    :returns: The prepared Task instance.
    """
    # test_workdir is an @property
    workdir = self.test_workdir

    # Bootstrap the tools needed by the task under test.
    # We need the bootstrap task's workdir to be under the test's .pants.d, so that it can
    # use artifact caching.  Making it a sibling of the main task's workdir achieves this.
    self.bootstrap_task_type.get_alternate_target_roots(context.options,
                                                        self.address_mapper,
                                                        self.build_graph)
    bootstrap_workdir = os.path.join(os.path.dirname(workdir), 'bootstrap_jvm_tools')
    self.bootstrap_task_type(context, bootstrap_workdir).execute()

    task = self.create_task(context, workdir)
    return task

  def execute(self, context):
    """Executes a jvm tool-using task, first bootstrapping any required jvm tools.

    Note: Other task pre-requisites will not be ensured and tests must instead setup their own
          product requirements if any.

    :API: public

    :returns: The Task instance that was executed.
    """
    task = self.prepare_execute(context)
    if not task.skip_execution:
      task.execute()
    return task
