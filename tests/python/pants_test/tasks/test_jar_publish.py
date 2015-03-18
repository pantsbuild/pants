# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import unittest2 as unittest

from mock import Mock
import pytest

from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.jvm.artifact import Artifact
from pants.backend.jvm.repository import Repository
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.jar_publish import JarPublish
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.exceptions import TaskError
from pants.scm.scm import Scm
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, safe_walk
from pants_test.tasks.test_base import TaskTest


class JarPublishTest(TaskTest):
  @classmethod
  def task_type(cls):
    return JarPublish

  def test_smoke_publish(self):
    with temporary_dir() as publish_dir:
      task = self.prepare_task(args=['--test-local=%s' % publish_dir],
                               build_graph=self.build_graph,
                               build_file_parser=self.build_file_parser)
      task.scm = Mock()
      task.execute()

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

  def _get_config(self):
    return """
[jar-publish]
repos: {
    'internal': {
      'resolver': 'example.com',
      'confs': ['default', 'sources', 'docs', 'changelog'],
    }
   }
"""

  def _prepare_mocks(self, task):
    task.scm = Mock()
    task.scm.changed_files = Mock(return_value=[])
    task._copy_artifact = Mock()
    task.create_source_jar = Mock()
    task.create_doc_jar = Mock()
    task.changelog = Mock(return_value="Many changes")
    task.publish = Mock()
    task.confirm_push = Mock(return_value=True)
    task.context.products.get = Mock(return_value=Mock())

  def test_publish_unlisted_repo(self):
    # Note that we set a different config here, so repos:internal has no config
    config = """
[jar-publish]
repos: {
    'another-repo': {
      'resolver': 'example.org',
      'confs': ['default', 'sources', 'docs', 'changelog'],
    }
  }
"""

    targets = self._prepare_for_publishing()
    with temporary_dir():
      task = self.prepare_task(config=config,
                               args=['--no-test-dryrun'],
                               build_graph=self.build_graph,
                               build_file_parser=self.build_file_parser,
                               targets=targets)
      self._prepare_mocks(task)
      with self.assertRaises(TaskError):
        try:
          task.execute()
        except TaskError as e:
          assert "Repository internal has no" in str(e)
          raise e

  def test_publish_local_dryrun(self):
    targets = self._prepare_for_publishing()

    with temporary_dir() as publish_dir:
      task = self.prepare_task(args=['--test-local=%s' % publish_dir],
                               build_graph=self.build_graph,
                               build_file_parser=self.build_file_parser,
                               targets=targets)
      self._prepare_mocks(task)
      task.execute()

      # Nothing is written to the pushdb during a dryrun publish
      # (maybe some directories are created, but git will ignore them)
      files = []
      for _, _, filenames in safe_walk(self.push_db_basedir):
        files.extend(filenames)
      self.assertEquals(0, len(files),
                        "Nothing should be written to the pushdb during a dryrun publish")

      self.assertEquals(0, task.confirm_push.call_count,
                        "Expected confirm_push not to be called")
      self.assertEquals(0, task.publish.call_count,
                        "Expected publish not to be called")

  def test_publish_local(self):
    for with_alias in [True, False]:
      targets = self._prepare_for_publishing(with_alias=with_alias)

      with temporary_dir() as publish_dir:
        task = self.prepare_task(args=['--test-local=%s' % publish_dir,
                                      '--no-test-dryrun'],
                                build_graph=self.build_graph,
                                build_file_parser=self.build_file_parser,
                                targets=targets)
        self._prepare_mocks(task)
        task.execute()

        #Nothing is written to the pushdb during a local publish
        #(maybe some directories are created, but git will ignore them)
        files = []
        for _, _, filenames in safe_walk(self.push_db_basedir):
          files.extend(filenames)
        self.assertEquals(0, len(files),
                          "Nothing should be written to the pushdb during a local publish")

        publishable_count = len(targets) - (1 if with_alias else 0)
        self.assertEquals(publishable_count, task.confirm_push.call_count,
                          "Expected one call to confirm_push per artifact")
        self.assertEquals(publishable_count, task.publish.call_count,
                          "Expected one call to publish per artifact")

  def test_publish_remote(self):
    targets = self._prepare_for_publishing()

    task = self.prepare_task(config=self._get_config(),
                             args=['--no-test-dryrun'],
                             build_graph=self.build_graph,
                             build_file_parser=self.build_file_parser,
                             targets=targets)
    self._prepare_mocks(task)
    task.execute()

    # One file per task is written to the pushdb during a local publish
    files = []
    for _, _, filenames in safe_walk(self.push_db_basedir):
      files.extend(filenames)

    self.assertEquals(len(targets), len(files),
                      "During a remote publish, one pushdb should be written per target")
    self.assertEquals(len(targets), task.confirm_push.call_count,
                      "Expected one call to confirm_push per artifact")
    self.assertEquals(len(targets), task.publish.call_count,
                      "Expected one call to publish per artifact")
    self.assertEquals(len(targets), task.scm.commit.call_count,
                      "Expected one call to scm.commit per artifact")
    self.assertEquals(len(targets), task.scm.add.call_count,
                      "Expected one call to scm.add per artifact")
    self.assertEquals(len(targets), task.scm.tag.call_count,
                      "Expected one call to scm.tag per artifact")

  def test_publish_retry_works(self):
    targets = self._prepare_for_publishing()

    task = self.prepare_task(config=self._get_config(),
                             args=['--no-test-dryrun',
                                   '--test-scm-push-attempts=3'],
                             build_graph=self.build_graph,
                             build_file_parser=self.build_file_parser,
                             targets=[targets[0]])
    self._prepare_mocks(task)

    task.scm.push = Mock()
    task.scm.push.side_effect = FailNTimes(2, Scm.RemoteException)
    task.execute()
    # Two failures, one success
    self.assertEquals(2 + 1, task.scm.push.call_count)

  def test_publish_retry_eventually_fails(self):
    targets = self._prepare_for_publishing()

    #confirm that we fail if we have too many failed push attempts
    task = self.prepare_task(config=self._get_config(),
                             args=['--no-test-dryrun',
                                   '--test-scm-push-attempts=3'],
                             build_graph=self.build_graph,
                             build_file_parser=self.build_file_parser,
                             targets=[targets[0]])
    self._prepare_mocks(task)
    task.scm.push = Mock()
    task.scm.push.side_effect = FailNTimes(3, Scm.RemoteException)
    with self.assertRaises(Scm.RemoteException):
      task.execute()

  def test_publish_local_only(self):
    with pytest.raises(TaskError) as exc:
      self.prepare_task()

class FailNTimes:
  def __init__(self, tries, exc_type, success=None):
    self.tries = tries
    self.exc_type = exc_type
    self.success = success
  def __call__(self, *args, **kwargs):
    self.tries -= 1
    if self.tries >= 0:
      raise self.exc_type()
    else:
      return self.success

class FailNTimesTest(unittest.TestCase):
  def test_fail_n_times(self):
    with self.assertRaises(ValueError):
      foo = Mock()
      foo.bar.side_effect = FailNTimes(1, ValueError)
      foo.bar()

    foo.bar()
