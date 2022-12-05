# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):
    outcome = yield
    rep = outcome.get_result()

    if (
        item.config.getoption("--noskip")
        and rep.skipped
        and (call.excinfo and call.excinfo.errisinstance(pytest.skip.Exception))
        and "no_error_if_skipped" not in item.keywords
    ):
        rep.outcome = "failed"
        assert call.excinfo is not None
        r = call.excinfo._getreprcrash()
        rep.longrepr = f"Forbidden skipped test - {r.message}"


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "no_error_if_skipped: Don't error if this test is skipped when using --noskip"
    )


def pytest_addoption(parser):
    parser.addoption(
        "--noskip", action="store_true", default=False, help="Treat skipped tests as errors"
    )
