# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.pantsd.pants_daemon_core import PantsDaemonCore
from pants.pantsd.service.pants_service import PantsServices
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class PantsDaemonCoreTest(TestBase):
    def test_prepare_scheduler(self):
        # A core with no services.
        def create_services(bootstrap_options, legacy_graph_scheduler):
            return PantsServices()

        core = PantsDaemonCore(create_services)

        first_scheduler = core.prepare_scheduler(create_options_bootstrapper(args=["-ldebug"]))
        second_scheduler = core.prepare_scheduler(create_options_bootstrapper(args=["-lwarn"]))

        assert first_scheduler is not second_scheduler
