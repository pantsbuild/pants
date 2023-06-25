# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import shutil
import stat
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from textwrap import dedent
from typing import Callable

import pytest


@pytest.fixture
def common_script_dir() -> Iterator[Path]:
    # common.sh is located in the same directory as this file due to a resources() dependency.
    common_script_path = Path(__file__).parent / "common.sh"
    with tempfile.TemporaryDirectory() as td:
        dir_path = Path(td)
        shutil.copyfile(common_script_path, dir_path / "common.sh")
        yield dir_path


@pytest.fixture
def create_test_script(common_script_dir: Path) -> Callable[[str, str], Path]:
    def _make_test_script(script_name: str, script_contents: str) -> Path:
        test_script_path = common_script_dir / script_name
        test_script_path.write_text(
            dedent(
                f"""\
        #!/usr/bin/env bash

        source {common_script_dir}/common.sh

        {script_contents}
        """
            )
        )
        test_script_path.chmod(test_script_path.stat().st_mode | stat.S_IXUSR)

        return test_script_path

    return _make_test_script


def test_log(create_test_script):
    test_script_path = create_test_script("log.sh", "log hey")

    assert subprocess.run([test_script_path], capture_output=True, check=True).stderr == b"hey\n"
