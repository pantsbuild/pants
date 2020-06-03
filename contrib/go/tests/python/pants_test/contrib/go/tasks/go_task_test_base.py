# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.task_test_base import TaskTestBase


class GoTaskTestBase(TaskTestBase):
    def context(self, for_task_types=None, **kwargs):
        options = kwargs.get("options", {})
        kwargs["options"] = options
        source = options.get("source", {})
        options["source"] = source
        if "root_patterns" not in source:
            source["root_patterns"] = [
                "src/go/src",
                "src/main/go/src",
                "3rdparty/go",
            ]
        return super().context(for_task_types, **kwargs)
