# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.task.noop_exec_task import NoopExecTask


class NoopCompile(NoopExecTask):
    """A no-op that provides a product type that can be used to force scheduling.

    :API: public
    """

    @classmethod
    def product_types(cls):
        return ["ran_compile"]


class NoopTest(NoopExecTask):
    """A no-op that provides a product type that can be used to force scheduling.

    :API: public
    """

    @classmethod
    def product_types(cls):
        return ["ran_tests"]
