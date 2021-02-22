# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.internals.native_engine import PyExecutor
from pants.pantsd.pants_daemon_core import PantsDaemonCore
from pants.pantsd.service.pants_service import PantsServices
from pants.testutil.option_util import create_options_bootstrapper


def test_prepare_scheduler():
    # A core with no services.
    def create_services(bootstrap_options, legacy_graph_scheduler):
        return PantsServices()

    core = PantsDaemonCore(create_options_bootstrapper([]), PyExecutor(2, 4), create_services)

    first_scheduler, first_options_initializer = core.prepare(
        create_options_bootstrapper(["-ldebug"])
    )
    second_scheduler, second_options_initializer = core.prepare(
        create_options_bootstrapper(["-lwarn"])
    )
    assert first_scheduler is not second_scheduler
    assert first_options_initializer is second_options_initializer
