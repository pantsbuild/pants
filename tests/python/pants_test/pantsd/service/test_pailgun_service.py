# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

import mock

from pants.pantsd.service.pailgun_service import PailgunService


PATCH_OPTS = dict(autospec=True, spec_set=True)


class FakePailgun(object):
  server_port = 33333


class TestPailgunService(unittest.TestCase):
  def setUp(self):
    self.mock_exiter_class = mock.Mock(side_effect=Exception('should not be called'))
    self.mock_runner_class = mock.Mock(side_effect=Exception('should not be called'))
    self.mock_scheduler_service = mock.Mock(side_effect=Exception('should not be called'))
    self.mock_spec_parser = mock.Mock(side_effect=Exception('should not be called'))
    self.service = PailgunService(bind_addr=(None, None),
                                  exiter_class=self.mock_exiter_class,
                                  runner_class=self.mock_runner_class,
                                  scheduler_service=self.mock_scheduler_service,
                                  spec_parser=self.mock_spec_parser)

  @mock.patch.object(PailgunService, '_setup_pailgun', **PATCH_OPTS)
  def test_pailgun_property_values(self, mock_setup):
    fake_pailgun = FakePailgun()
    mock_setup.return_value = fake_pailgun
    self.assertIs(self.service.pailgun, fake_pailgun)
    self.assertEqual(self.service.pailgun_port, 33333)
