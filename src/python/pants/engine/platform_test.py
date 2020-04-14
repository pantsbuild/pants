# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.fs import EMPTY_DIRECTORY_DIGEST
from pants.engine.isolated_process import (
    Process,
    FallibleProcessResultWithPlatform,
)
from pants.engine.platform import Platform
from pants.testutil.test_base import TestBase


class PlatformTest(TestBase):
    def test_platform_on_local_epr_result(self) -> None:

        this_platform = Platform.current

        req = Process(
            argv=("/bin/echo", "test"),
            input_files=EMPTY_DIRECTORY_DIGEST,
            description="Run some program that will exit cleanly.",
        )
        result = self.request_single_product(FallibleProcessResultWithPlatform, req)
        assert result.exit_code == 0
        assert result.platform == this_platform
