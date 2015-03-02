# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from mock import Mock

from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.jvm.artifact import Artifact
from pants.backend.jvm.repository import Repository
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.artifact import Artifact
from pants.backend.jvm.repository import Repository
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.jar_artifact_publish import JarArtifactPublish
from pants.base.build_file_aliases import BuildFileAliases
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, safe_walk
from pants_test.task_test_base import TaskTestBase


class JarArtifactPublishTest(object):
  @property
  def alias_groups(self):
    self.push_db_basedir = os.path.join(self.build_root, "pushdb")
    safe_mkdir(self.push_db_basedir)

    return BuildFileAliases.create(
      targets={
        'jar_library': JarLibrary,
        'java_library': JavaLibrary,
        'target': Dependencies,
        },
      objects={
        'artifact': Artifact,
        'internal': Repository(name='internal', url='http://example.com',
                               push_db_basedir=self.push_db_basedir),
        },
      )

  def _prepare_for_publishing(self, with_alias=False):
    targets = {}
    targets['a'] = self.create_library('a', 'java_library', 'a', ['A.java'],
                                       provides="""artifact(org='com.example', name='nail', repo=internal)""")

    targets['b'] = self.create_library('b', 'java_library', 'b', ['B.java'],
                                       provides="""artifact(org='com.example', name='shoe', repo=internal)""",
                                       dependencies=['a'])

    if with_alias:
      # add an alias target between c and b
      targets['z'] = self.create_library('z', 'target', 'z', dependencies=['b'])
      c_deps = ['z']
    else:
      c_deps = ['b']

    targets['c'] = self.create_library('c', 'java_library', 'c', ['C.java'],
                                       provides="""artifact(org='com.example', name='horse', repo=internal)""",
                                       dependencies=c_deps)
    return targets.values()

  def _get_repos(self):
    return {
      'internal': {
        'resolver': 'example.com',
        'confs': ['default', 'sources', 'docs', 'changelog'],
        }
    }

  def _prepare_mocks(self, task):
    task.scm = Mock()
    task.scm.changed_files = Mock(return_value=[])
    task._copy_artifact = Mock()
    task.create_source_jar = Mock()
    task.create_doc_jar = Mock()
    task.changelog = Mock(return_value="Many changes")
    task.publish = Mock()
    task.confirm_push = Mock(return_value=True)

  def test_smoke_publish(self):
    with temporary_dir() as publish_dir:
      self.set_options(local=publish_dir)
      task = self.create_task(self.context())
      task.scm = Mock()
      task.execute()

  def publish_local(self, publishable_count=None):
    for with_alias in [True, False]:
      targets = self._prepare_for_publishing(with_alias=with_alias)

      with temporary_dir() as publish_dir:
        self.set_options(dryrun=False, local=publish_dir)
        task = self.create_task(self.context(target_roots=targets))
        self._prepare_mocks(task)
        task.execute()

        #Nothing is written to the pushdb during a local publish
        #(maybe some directories are created, but git will ignore them)
        files = []
        for _, _, filenames in safe_walk(self.push_db_basedir):
          files.extend(filenames)
        self.assertEquals(0, len(files),
                          "Nothing should be written to the pushdb during a local publish")
        if not publishable_count:
          publishable_count = len(targets) - (1 if with_alias else 0)

        self.assertEquals(publishable_count, task.confirm_push.call_count,
                          "Expected one call to confirm_push per artifact")
        self.assertEquals(publishable_count, task.publish.call_count,
                          "Expected one call to publish per artifact")


class JarArtifactPublishDerivedTest(JarArtifactPublishTest, TaskTestBase):
  class TestJarArtifactPublish(JarArtifactPublish):
    @property
    def jar_product_type(self):
      return 'jars'

    @property
    def artifact_ext(self):
      return 'foo'

    @property
    def classifier(self):
      return 'foo'

    def exported_targets(self):
      return self.context.targets(lambda t: t.name == 'a')

  @classmethod
  def task_type(cls):
    return JarArtifactPublishDerivedTest.TestJarArtifactPublish

  def  test_publish_local(self):
    self.publish_local(1)