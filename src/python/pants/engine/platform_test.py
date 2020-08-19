# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResultWithPlatform, Process
from pants.engine.rules import QueryRule
from pants.testutil.test_base import TestBase


class PlatformTest(TestBase):
    @classmethod
    def rules(cls):
        return (*super().rules(), QueryRule(FallibleProcessResultWithPlatform, (Process,)))

    def test_platform_on_local_epr_result(self) -> None:
        this_platform = Platform.current
        process = Process(
            argv=("/bin/echo", "test"), description="Run some program that will exit cleanly."
        )
        result = self.request_product(FallibleProcessResultWithPlatform, process)
        assert result.exit_code == 0
        assert result.platform == this_platform
