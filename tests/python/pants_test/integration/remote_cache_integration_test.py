# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.internals.native_engine import PyStubCAS
from pants.option.global_options import RemoteCacheWarningsBehavior
from pants.option.scope import GLOBAL_SCOPE_CONFIG_SECTION
from pants.testutil.pants_integration_test import run_pants


def test_warns_on_remote_cache_errors():
    cas = PyStubCAS.builder().always_errors().build()

    def run(behavior: RemoteCacheWarningsBehavior) -> str:
        pants_run = run_pants(
            [
                "--backend-packages=['pants.backend.python']",
                "--no-dynamic-ui",
                "package",
                "testprojects/src/python/hello/main:main",
            ],
            use_pantsd=False,
            config={
                GLOBAL_SCOPE_CONFIG_SECTION: {
                    "remote_cache_read": True,
                    "remote_cache_write": True,
                    "remote_cache_warnings": behavior.value,
                    # NB: Our options code expects `grpc://`, which it will then convert back to
                    # `http://` before sending over FFI.
                    "remote_store_address": cas.address.replace("http://", "grpc://"),
                }
            },
        )
        pants_run.assert_success()
        return pants_run.stderr

    def read_err(i: int) -> str:
        return f"Failed to read from remote cache ({i} occurrences so far): Unimplemented"

    def write_err(i: int) -> str:
        return (
            f'Failed to write to remote cache ({i} occurrences so far): Internal: "StubCAS is '
            f'configured to always fail"'
        )

    first_read_err = read_err(1)
    first_write_err = write_err(1)
    third_read_err = read_err(3)
    third_write_err = write_err(3)
    fourth_read_err = read_err(4)
    fourth_write_err = write_err(4)

    ignore_result = run(RemoteCacheWarningsBehavior.ignore)
    for err in [
        first_read_err,
        first_write_err,
        third_read_err,
        third_write_err,
        fourth_read_err,
        fourth_write_err,
    ]:
        assert err not in ignore_result

    first_only_result = run(RemoteCacheWarningsBehavior.first_only)
    for err in [first_read_err, first_write_err]:
        assert err in first_only_result
    for err in [third_read_err, third_write_err, fourth_read_err, fourth_write_err]:
        assert err not in first_only_result

    backoff_result = run(RemoteCacheWarningsBehavior.backoff)
    for err in [first_read_err, first_write_err, fourth_read_err, fourth_write_err]:
        assert err in backoff_result
    for err in [third_read_err, third_write_err]:
        assert err not in backoff_result
