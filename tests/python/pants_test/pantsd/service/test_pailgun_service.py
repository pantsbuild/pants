# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
import unittest.mock

from pants.pantsd.service.pailgun_service import PailgunService


PATCH_OPTS = dict(autospec=True, spec_set=True)


class FakePailgun:
    server_port = 33333


class TestPailgunService(unittest.TestCase):
    def setUp(self):
        self.mock_exiter_class = unittest.mock.Mock(side_effect=Exception("should not be called"))
        self.mock_runner_class = unittest.mock.Mock(side_effect=Exception("should not be called"))
        self.mock_scheduler_service = unittest.mock.Mock(
            side_effect=Exception("should not be called")
        )
        self.mock_target_roots_calculator = unittest.mock.Mock(
            side_effect=Exception("should not be called")
        )
        self.service = PailgunService(
            bind_addr=(None, None),
            runner_class=self.mock_runner_class,
            scheduler_service=self.mock_scheduler_service,
            shutdown_after_run=False,
        )

    @unittest.mock.patch.object(PailgunService, "_setup_pailgun", **PATCH_OPTS)
    def test_pailgun_property_values(self, mock_setup):
        fake_pailgun = FakePailgun()
        mock_setup.return_value = fake_pailgun
        self.assertIs(self.service.pailgun, fake_pailgun)
        self.assertEqual(self.service.pailgun_port, 33333)

    @unittest.mock.patch.object(PailgunService, "terminate", **PATCH_OPTS)
    def test_pailgun_service_closes_when_callback_is_called(self, mock_setup):
        fake_pailgun = FakePailgun()
        mock_setup.return_value = fake_pailgun
        self.service._shutdown_after_run = True
        self.service._request_complete_callback()
        self.assertIs(self.service.terminate.called, True)
