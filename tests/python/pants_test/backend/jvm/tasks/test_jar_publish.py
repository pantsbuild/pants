# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from mock import Mock

from pants.backend.jvm.artifact import Artifact
from pants.backend.jvm.repository import Repository
from pants.backend.jvm.scala_artifact import ScalaArtifact
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.jar_publish import JarPublish
from pants.base.exceptions import TaskError
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.target import Target
from pants.scm.scm import Scm
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, safe_walk
from pants_test.tasks.task_test_base import TaskTestBase


class JarPublishTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return JarPublish

  def test_smoke_publish(self):
    with temporary_dir() as publish_dir:
      self.set_options(local=publish_dir)
      task = self.create_task(self.context())
      task.scm = Mock()
      task.execute()

  @property
  def alias_groups(self):
    self.push_db_basedir = os.path.join(self.build_root, "pushdb")
    safe_mkdir(self.push_db_basedir)

    return BuildFileAliases(
      targets={
        'jar_library': JarLibrary,
        'java_library': JavaLibrary,
        'target': Target,
      },
      objects={
        'artifact': Artifact,
        'scala_artifact': ScalaArtifact,
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

  def _prepare_targets_with_duplicates(self):
    targets = list(self._prepare_for_publishing())
    conflict = self.create_library(
      'conflict', 'java_library', 'conflict', ['Conflict.java'],
      provides="""artifact(org='com.example', name='nail', repo=internal)""",
    )
    targets.append(conflict)
    return targets

  def _get_repos(self):
    return {
      'internal': {
        'resolver': 'example.com',
      }
    }

  def _prepare_mocks(self, task):
    task.scm = Mock()
    task.scm.changed_files = Mock(return_value=[])
    task._copy_artifact = Mock()
    task.create_source_jar = Mock()
    task.create_doc_jar = Mock()
    task.changelog = Mock(return_value='Many changes')
    task.publish = Mock()
    task.confirm_push = Mock(return_value=True)
    task.context.products.get = Mock(return_value=Mock())

  def test_publish_unlisted_repo(self):
    # Note that we set a different config here, so repos:internal has no config
    repos = {
      'another-repo': {
        'resolver': 'example.org',
      }
    }

    targets = self._prepare_for_publishing()
    with temporary_dir():
      self.set_options(dryrun=False, repos=repos)
      task = self.create_task(self.context(target_roots=targets))
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
      self.set_options(local=publish_dir)
      task = self.create_task(self.context(target_roots=targets))
      self._prepare_mocks(task)
      task.execute()

      # Nothing is written to the pushdb during a dryrun publish
      # (maybe some directories are created, but git will ignore them)
      files = []
      for _, _, filenames in safe_walk(self.push_db_basedir):
        files.extend(filenames)
      self.assertEquals(0, len(files),
                        'Nothing should be written to the pushdb during a dryrun publish')

      self.assertEquals(0, task.confirm_push.call_count,
                        'Expected confirm_push not to be called')
      self.assertEquals(0, task.publish.call_count,
                        'Expected publish not to be called')

  def test_publish_local(self):
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
                          'Nothing should be written to the pushdb during a local publish')

        publishable_count = len(targets) - (1 if with_alias else 0)
        self.assertEquals(publishable_count, task.confirm_push.call_count,
                          'Expected one call to confirm_push per artifact')
        self.assertEquals(publishable_count, task.publish.call_count,
                          'Expected one call to publish per artifact')

  def test_publish_remote(self):
    targets = self._prepare_for_publishing()
    self.set_options(dryrun=False, repos=self._get_repos(), push_postscript='\nPS')
    task = self.create_task(self.context(target_roots=targets))
    self._prepare_mocks(task)
    task.execute()

    # One file per task is written to the pushdb during a local publish
    files = []
    for _, _, filenames in safe_walk(self.push_db_basedir):
      files.extend(filenames)

    self.assertEquals(len(targets), len(files),
                      'During a remote publish, one pushdb should be written per target')
    self.assertEquals(len(targets), task.confirm_push.call_count,
                      'Expected one call to confirm_push per artifact')
    self.assertEquals(len(targets), task.publish.call_count,
                      'Expected one call to publish per artifact')

    self.assertEquals(len(targets), task.scm.commit.call_count,
                      'Expected one call to scm.commit per artifact')
    args, kwargs = task.scm.commit.call_args
    message = args[0]
    message_lines = message.splitlines()
    self.assertTrue(len(message_lines) > 1,
                    'Expected at least one commit message line in addition to the post script.')
    self.assertEquals('PS', message_lines[-1])

    self.assertEquals(len(targets), task.scm.add.call_count,
                      'Expected one call to scm.add per artifact')

    self.assertEquals(len(targets), task.scm.tag.call_count,
                      'Expected one call to scm.tag per artifact')
    args, kwargs = task.scm.tag.call_args
    tag_name, tag_message = args
    tag_message_splitlines = tag_message.splitlines()
    self.assertTrue(len(tag_message_splitlines) > 1,
                    'Expected at least one tag message line in addition to the post script.')
    self.assertEquals('PS', tag_message_splitlines[-1])

  def test_publish_retry_works(self):
    targets = self._prepare_for_publishing()
    self.set_options(dryrun=False, scm_push_attempts=3, repos=self._get_repos())
    task = self.create_task(self.context(target_roots=targets[0:1]))
    self._prepare_mocks(task)

    task.scm.push = Mock()
    task.scm.push.side_effect = FailNTimes(2, Scm.RemoteException)
    task.execute()
    # Two failures, one success
    self.assertEquals(2 + 1, task.scm.push.call_count)

  def test_publish_retry_eventually_fails(self):
    targets = self._prepare_for_publishing()

    #confirm that we fail if we have too many failed push attempts
    self.set_options(dryrun=False, scm_push_attempts=3, repos=self._get_repos())
    task = self.create_task(self.context(target_roots=targets[0:1]))
    self._prepare_mocks(task)
    task.scm.push = Mock()
    task.scm.push.side_effect = FailNTimes(3, Scm.RemoteException)
    with self.assertRaises(Scm.RemoteException):
      task.execute()

  def test_publish_retry_fails_immediately_with_exception_on_refresh_failure(self):
    targets = self._prepare_for_publishing()
    self.set_options(dryrun=False, scm_push_attempts=3, repos=self._get_repos())
    task = self.create_task(self.context(target_roots=targets[0:1]))

    self._prepare_mocks(task)
    task.scm.push = Mock()
    task.scm.push.side_effect = FailNTimes(3, Scm.RemoteException)
    task.scm.refresh = Mock()
    task.scm.refresh.side_effect = FailNTimes(1, Scm.LocalException)

    with self.assertRaises(Scm.LocalException):
      task.execute()
    self.assertEquals(1, task.scm.push.call_count)

  def test_publish_local_only(self):
    with self.assertRaises(TaskError):
      self.create_task(self.context())

  def test_check_targets_fails_with_duplicate_artifacts(self):
    bad_targets = self._prepare_targets_with_duplicates()
    with temporary_dir() as publishdir:
      self.set_options(dryrun=False, local=publishdir)
      task = self.create_task(self.context(target_roots=bad_targets))
      self._prepare_mocks(task)
      with self.assertRaises(JarPublish.DuplicateArtifactError):
        task.check_targets(task.exported_targets())


class FailNTimes(object):

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


class JarPublishAuthTest(TaskTestBase):
  """Tests for backend jvm JarPublish class"""

  def _default_jvm_opts(self):
    """Return a fresh copy of this list every time."""
    return ['jvm_opt_1', 'jvm_opt_2']

  @classmethod
  def task_type(cls):
    return JarPublish

  def setUp(self):
    super(JarPublishAuthTest, self).setUp()

    self.set_options(
      jvm_options=['-Dfoo=bar'],
      repos={
        'some_ext_repo': {
          'resolver': 'artifactory.foobar.com',
          'confs': ['default', 'sources'],
          'auth': '',
          'help': 'You break it, you bought it',
        }
      }
    )
    context = self.context()
    self._jar_publish = self.create_task(context)

  def test_options_with_no_auth(self):
    """When called without authentication credentials, `JarPublish._ivy_jvm_options()` shouldn't
    modify any options.
    """
    self._jar_publish._jvm_options = self._default_jvm_opts()
    repo = {}
    modified_opts = self._jar_publish._ivy_jvm_options(repo)
    self.assertEqual(modified_opts, self._default_jvm_opts())

  def test_options_with_auth(self):
    """`JarPublish._ivy_jvm_options()` should produce the same list, when called multiple times
    with authentication credentials.
    """
    self._jar_publish._jvm_options = self._default_jvm_opts()

    username = 'mjk'
    password = 'h.'
    creds_options = ['-Dlogin={}'.format(username), '-Dpassword={}'.format(password)]

    repo = {
      'auth': 'blah',
      'username': username,
      'password': password,
    }
    modified_opts = self._jar_publish._ivy_jvm_options(repo)
    self.assertEqual(modified_opts, self._default_jvm_opts() + creds_options)

    # Now run it again, and make sure we don't get dupes.
    modified_opts = self._jar_publish._ivy_jvm_options(repo)
    self.assertEqual(modified_opts, self._default_jvm_opts() + creds_options)
