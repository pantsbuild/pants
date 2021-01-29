# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.internals.native_engine import PyExecutor
from pants.init.options_initializer import OptionsInitializer
from pants.pantsd.pants_daemon_core import PantsDaemonCore
from pants.pantsd.service.pants_service import PantsServices
from pants.testutil.option_util import create_options_bootstrapper


def test_prepare_scheduler():
    debug_ob = create_options_bootstrapper(["-ldebug"])
    warn_ob = create_options_bootstrapper(["-lwarn"])
    debug_build_config, debug_options = OptionsInitializer.create_with_build_config(
        debug_ob, raise_=False
    )
    warn_build_config, warn_options = OptionsInitializer.create_with_build_config(
        warn_ob, raise_=False
    )

    # A core with no services.
    def create_services(bootstrap_options, legacy_graph_scheduler):
        return PantsServices()

    core = PantsDaemonCore(PyExecutor(2, 4), create_services)

    first_scheduler = core.prepare_scheduler(debug_ob, debug_options, debug_build_config)
    second_scheduler = core.prepare_scheduler(warn_ob, warn_options, warn_build_config)
    assert first_scheduler is not second_scheduler
