# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re

from pants.engine.internals.native_engine import PyExecutor, PyStubCAS
from pants.option.scope import GLOBAL_SCOPE_CONFIG_SECTION
from pants.testutil.pants_integration_test import run_pants


def test_warns_on_remote_cache_errors():
    executor = PyExecutor(2, 4)
    builder = PyStubCAS.builder()
    builder.always_errors()
    cas = builder.build(executor)

    pants_run = run_pants(
        [
            "--backend-packages=['pants.backend.python']",
            "--no-dynamic-ui",
            "--level=info",
            "package",
            "testprojects/src/python/hello/main:main",
        ],
        use_pantsd=False,
        config={
            GLOBAL_SCOPE_CONFIG_SECTION: {
                "remote_cache_read": True,
                "remote_cache_write": True,
                # NB: Our options code expects `grpc://`, which it will then convert back to
                # `http://` before sending over FFI.
                "remote_store_address": cas.address().replace("http://", "grpc://"),
            }
        },
    )

    pants_run.assert_success()
    assert "Failed to read from remote cache: Unimplemented" in pants_run.stderr
    assert (
        re.search(
            "Failed to write to remote cache:.*StubCAS is configured to always fail",
            pants_run.stderr,
            re.MULTILINE,
        )
        is not None
    )
