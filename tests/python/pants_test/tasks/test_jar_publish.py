# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

import pytest
from mock import Mock

from pants.backend.jvm.tasks.jar_publish import JarPublish
from pants.base.exceptions import TaskError
from pants.scm.scm import Scm
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_walk
from pants_test.task_test_base import TaskTestBase
from pants_test.tasks.test_jar_artifact_publish import JarArtifactPublishTest


class JarPublishTest(JarArtifactPublishTest, TaskTestBase):
  @classmethod
  def task_type(cls):
    return JarPublish

  def test_publish_unlisted_repo(self):
    # Note that we set a different config here, so repos:internal has no config
    repos = {
      'another-repo': {
        'resolver': 'example.org',
        'confs': ['default', 'sources', 'docs', 'changelog'],
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
                        "Nothing should be written to the pushdb during a dryrun publish")

      self.assertEquals(0, task.confirm_push.call_count,
                        "Expected confirm_push not to be called")
      self.assertEquals(0, task.publish.call_count,
                        "Expected publish not to be called")

  def test_publish_remote(self):
    targets = self._prepare_for_publishing()
    self.set_options(dryrun=False, repos=self._get_repos())
    task = self.create_task(self.context(target_roots=targets))
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
    self.assertEquals(len(targets), task.scm.tag.call_count,
                      "Expected one call to scm.tag per artifact")

  def test_publish_local(self):
    self.publish_local()

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

  def test_publish_local_only(self):
    with pytest.raises(TaskError):
      self.create_task(self.context())

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
