# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import mock
import psutil

from pants.java.nailgun_executor import NailgunExecutor
from pants_test.test_base import TestBase


PATCH_OPTS = dict(autospec=True, spec_set=True)


def fake_process(**kwargs):
  proc = mock.create_autospec(psutil.Process, spec_set=True)
  [setattr(getattr(proc, k), 'return_value', v) for k, v in kwargs.items()]
  return proc


class NailgunExecutorTest(TestBase):
  def setUp(self):
    super(NailgunExecutorTest, self).setUp()
    self.executor = NailgunExecutor(identity='test',
                                    workdir='/__non_existent_dir',
                                    nailgun_classpath=[],
                                    distribution=mock.Mock(),
                                    metadata_base_dir=self.subprocess_dir)

  def test_is_alive_override(self):
    with mock.patch.object(NailgunExecutor, '_as_process', **PATCH_OPTS) as mock_as_process:
      mock_as_process.return_value = fake_process(
        name='java',
        pid=3,
        status=psutil.STATUS_IDLE,
        cmdline=[b'java', b'-arg', NailgunExecutor._PANTS_NG_BUILDROOT_ARG]
      )
      self.assertTrue(self.executor.is_alive())
      mock_as_process.assert_called_with(self.executor)

  def test_is_alive_override_not_my_process(self):
    with mock.patch.object(NailgunExecutor, '_as_process', **PATCH_OPTS) as mock_as_process:
      mock_as_process.return_value = fake_process(
        name='java',
        pid=3,
        status=psutil.STATUS_IDLE,
        cmdline=[b'java', b'-arg', b'-arg2']
      )
      self.assertFalse(self.executor.is_alive())
      mock_as_process.assert_called_with(self.executor)
