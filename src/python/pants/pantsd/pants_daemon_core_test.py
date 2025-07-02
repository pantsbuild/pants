# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.env_vars import CompleteEnvironmentVars
from pants.engine.internals.native_engine import PyExecutor
from pants.pantsd.pants_daemon_core import PantsDaemonCore
from pants.pantsd.service.pants_service import PantsServices
from pants.testutil.option_util import create_options_bootstrapper


def test_prepare_scheduler() -> None:
    # A core with no services.
    def create_services(bootstrap_options, graph_scheduler):
        return PantsServices()

    env = CompleteEnvironmentVars({})
    core = PantsDaemonCore(
        create_options_bootstrapper([]),
        PyExecutor(core_threads=2, max_threads=4),
        create_services,
    )

    first_scheduler, first_options_initializer = core.prepare(
        create_options_bootstrapper(["-ldebug"]),
        env,
    )
    second_scheduler, second_options_initializer = core.prepare(
        create_options_bootstrapper(["-lwarn"]),
        env,
    )
    assert first_scheduler is not second_scheduler
    assert first_options_initializer is second_options_initializer
