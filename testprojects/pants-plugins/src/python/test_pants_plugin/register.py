# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from test_pants_plugin.pants_testutil_tests import PantsTestutilTests
from test_pants_plugin.subsystems.pants_testutil_subsystem import PantsTestutilSubsystem
from test_pants_plugin.tasks.deprecation_warning_task import DeprecationWarningTask
from test_pants_plugin.tasks.lifecycle_stub_task import LifecycleStubTask

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
    return BuildFileAliases(
        context_aware_object_factories={"pants_testutil_tests": PantsTestutilTests,}
    )


def register_goals():
    task(name="deprecation-warning-task", action=DeprecationWarningTask).install()
    task(name="lifecycle-stub-task", action=LifecycleStubTask).install("lifecycle-stub-goal")


def global_subsystems():
    return (PantsTestutilSubsystem,)


if os.environ.get("_RAISE_KEYBOARDINTERRUPT_ON_IMPORT", False):
    raise KeyboardInterrupt("ctrl-c during import!")
