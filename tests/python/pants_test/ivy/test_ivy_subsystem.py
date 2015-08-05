# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.task import Task
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.util.contextutil import environment_as
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase


class DummyIvyTask(Task):
  """A placeholder task used as a hint to BaseTest to initialize the Bootstrapper subsystem."""
  @classmethod
  def options_scope(cls):
    return 'dummy-ivy-task'

  @classmethod
  def global_subsystems(cls):
    return super(DummyIvyTask, cls).global_subsystems() + (IvySubsystem, )


class IvySubsystemTest(JvmToolTaskTestBase):

  @classmethod
  def task_type(cls):
    return DummyIvyTask

  def setUp(self):
    super(IvySubsystemTest, self).setUp()
    # Calling self.context() is a hack to make sure subsystems are initialized.
    self.context()

  def test_parse_proxy_string(self):
    ivy_subsystem =IvySubsystem.global_instance()

    self.assertEquals(('example.com', 1234),
                      ivy_subsystem._parse_proxy_string('http://example.com:1234'))
    self.assertEquals(('secure-example.com', 999),
                      ivy_subsystem._parse_proxy_string('http://secure-example.com:999'))
    # trailing slash is ok
    self.assertEquals(('example.com', 1234),
                      ivy_subsystem._parse_proxy_string('http://example.com:1234/'))

  def test_proxy_from_env(self):
    ivy_subsystem = IvySubsystem.global_instance()

    self.assertIsNone(ivy_subsystem.http_proxy())
    self.assertIsNone(ivy_subsystem.https_proxy())

    with environment_as(HTTP_PROXY='http://proxy.example.com:456',
                        HTTPS_PROXY='https://secure-proxy.example.com:789'):
      self.assertEquals('http://proxy.example.com:456', ivy_subsystem.http_proxy())
      self.assertEquals('https://secure-proxy.example.com:789', ivy_subsystem.https_proxy())

      self.assertEquals([
        '-Dhttp.proxyHost=proxy.example.com',
        '-Dhttp.proxyPort=456',
        '-Dhttps.proxyHost=secure-proxy.example.com',
        '-Dhttps.proxyPort=789',
      ], ivy_subsystem.extra_jvm_options())
