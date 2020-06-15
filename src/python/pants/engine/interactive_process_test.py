# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.engine.fs import Digest
from pants.engine.interactive_process import InteractiveProcess


def test_running_in_workspace_cannot_have_input_files() -> None:
    mock_digest = Digest("fake", 1)
    with pytest.raises(ValueError):
        InteractiveProcess(argv=["/bin/echo"], input_digest=mock_digest, run_in_workspace=True)
