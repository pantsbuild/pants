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
        assert not test_script_path.exists()
        test_script_path.write_text(
            dedent(
                f"""#!/usr/bin/env bash
        source {common_script_dir}/common.sh
        {script_contents}
        """
            )
        )
        test_script_path.chmod(test_script_path.stat().st_mode | stat.S_IXUSR)

        return test_script_path

    return _make_test_script


def test_log(create_test_script):
    log_script = create_test_script("log.sh", "log hey")

    assert subprocess.run([log_script], capture_output=True, check=True).stderr == b"hey\n"


def test_determine_python(create_test_script):
    success_script = create_test_script("python-success.sh", "determine_python")
    success_py = subprocess.run([success_script], capture_output=True, check=True).stdout.rstrip(
        b"\n"
    )
    subprocess.run([success_py, "--version"], capture_output=True, check=True).stdout.startswith(
        b"Python 3.9"
    )

    no_interpreter_script = create_test_script(
        "python-no-interpreter.sh",
        dedent(
            """
    export _PANTS_SOURCE_PY_VERSION=version-should-not-exist
    determine_python
    """
        ),
    )
    result = subprocess.run([no_interpreter_script], capture_output=True)
    assert result.returncode == 1
    assert (
        result.stderr.decode().rstrip("\n")
        == "pants: Failed to find a Python version-should-not-exist interpreter.\nYou may explicitly select a Python interpreter path by setting $PY"
    )

    with tempfile.TemporaryDirectory() as td:
        hack_pyenv_exe_dir = Path(td)
        pyenv_shim = hack_pyenv_exe_dir / "pythonhack-pyenv"
        pyenv_shim.write_text(
            dedent(
                f"""#!/usr/bin/env bash
        echo >&2 'pyenv: pythonhack-pyenv: command not found'
        """
            )
        )
        pyenv_shim.chmod(pyenv_shim.stat().st_mode | stat.S_IXUSR)

        hardcoded_py_script = create_test_script(
            "hardcoded-pyenv-path.sh", f"PY={pyenv_shim} determine_python"
        )
        assert subprocess.run(
            [hardcoded_py_script], capture_output=True, check=True
        ).stdout.decode().rstrip("\n") == str(pyenv_shim)

        pyenv_hack_script = create_test_script(
            "pyenv-hack.sh",
            dedent(
                f"""
        export _PANTS_SOURCE_PY_VERSION=hack-pyenv
        export PATH="${{PATH}}:{hack_pyenv_exe_dir}"
        determine_python
        """
            ),
        )
        result = subprocess.run([pyenv_hack_script], capture_output=True)
        assert result.returncode == 1
        assert (
            result.stderr.decode().rstrip("\n")
            == f"pants: The Python hack-pyenv interpreter at {pyenv_shim} is an inactive pyenv interpreter"
        )
