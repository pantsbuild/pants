# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.testutil.pants_integration_test import run_pants


@pytest.mark.parametrize("use_pantsd", [True, False])
def test_pants_bin_name(use_pantsd) -> None:
    pants_run = run_pants(
        ["--pants-bin-name='./pantsV2'", "help", "target"],
        use_pantsd=use_pantsd,
    )
    pants_run.assert_success()
    assert "Use `'./pantsV2' list --documented ::`" in pants_run.stdout
