# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
from unittest import mock

from pants.pantsd.service.pailgun_service import PailgunService

PATCH_OPTS = dict(autospec=True, spec_set=True)


class TestPailgunService(unittest.TestCase):
    def setUp(self):
        self.mock_runner = mock.Mock(side_effect=Exception("should not be called"))
        self.mock_scheduler_service = mock.Mock(side_effect=Exception("should not be called"))

    @mock.patch.object(PailgunService, "terminate", **PATCH_OPTS)
    @mock.patch.object(PailgunService, "_setup_server", **PATCH_OPTS)
    @mock.patch.object(PailgunService, "pailgun_port", **PATCH_OPTS)
    def test_pailgun_service_exits_on_error(self, mock_port, mock_setup, mock_terminate):
        import logging

        logging.getLogger().addHandler(logging.StreamHandler())

        mock_port.side_effect = [33333, Exception("Goodbye.")]
        service = PailgunService(
            port_requested=0,
            runner=self.mock_runner,
            scheduler_service=self.mock_scheduler_service,
        )
        service.run()
        self.assertIs(mock_terminate.called, True)
