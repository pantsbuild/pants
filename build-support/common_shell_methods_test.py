# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import shutil
import stat
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from textwrap import dedent

import pytest


@pytest.fixture
def script_dir() -> Iterator[Path]:
    common_script_path = Path(__file__).parent / 'common.sh'
    with tempfile.TemporaryDirectory() as td:
        dir_path = Path(td)
        shutil.copyfile(common_script_path, dir_path / 'common.sh')
        yield dir_path

def test_log(script_dir: Path):
    test_script_path = script_dir / 'log.sh'
    test_script_path.write_text(dedent(f"""\
    #!/usr/bin/env bash

    source {script_dir}/common.sh

    log hey
    """))
    test_script_path.chmod(test_script_path.stat().st_mode | stat.S_IXUSR)

    assert subprocess.run([test_script_path], capture_output=True, check=True).stderr == b'hey\n'
