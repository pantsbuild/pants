# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_integration_test import run_pants


def test_pants_bin_name() -> None:
    def ask_for_help(use_pantsd: bool) -> str:
        pants_run = run_pants(
            ["--pants-bin-name='./pantsV2'", "help", "target"],
            use_pantsd=use_pantsd,
        )
        pants_run.assert_success()
        return pants_run.stdout

    assert "Use `'./pantsV2' list --documented ::`" in ask_for_help(False)
    assert "Use `'./pantsV2' list --documented ::`" in ask_for_help(True)
