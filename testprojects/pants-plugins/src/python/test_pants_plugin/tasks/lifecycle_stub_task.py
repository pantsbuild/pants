# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from test_pants_plugin.subsystems.lifecycle_stubs import LifecycleStubs

from pants.base.exception_sink import ExceptionSink
from pants.task.task import Task
from pants.util.memo import memoized_property


class LifecycleStubTask(Task):
    """A task which raises an Exception on execution which is used to test Pants shutdown
    behavior."""

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (LifecycleStubs.scoped(cls),)

    @memoized_property
    def _lifecycle_stubs(self):
        return LifecycleStubs.scoped_instance(self)

    def execute(self):
        output_file = self._lifecycle_stubs.new_interactive_stream_output_file
        if output_file:
            file_stream = open(output_file, "wb")
            ExceptionSink.reset_interactive_output_stream(file_stream, output_file)

        raise Exception("erroneous!")
