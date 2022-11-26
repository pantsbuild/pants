# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
from pathlib import Path


def test_touch_ignored_dir() -> None:
    ignored_dir = Path(os.environ["IGNORED_DIR"]).resolve()
    ignored_dir.touch()
