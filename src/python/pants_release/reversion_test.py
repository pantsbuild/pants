# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import requests
from pants_release.reversion import reversion


def test_reversion(tmp_path: Path) -> None:
    # Download an input whl.
    name_template = "ansicolors-{}-py2.py3-none-any.whl"
    input_version = "1.1.8"
    input_name = name_template.format(input_version)
    url = (
        "https://files.pythonhosted.org/packages/53/18/"
        "a56e2fe47b259bb52201093a3a9d4a32014f9d85071ad07e9d60600890ca/{}".format(input_name)
    )
    input_whl_file = tmp_path / input_name
    with input_whl_file.open(mode="wb") as f:
        shutil.copyfileobj(requests.get(url, stream=True).raw, f)

    # Rewrite it.
    output_version = "9.1.9"
    output_name = name_template.format(output_version)
    output_whl_file = tmp_path / output_name

    reversion(
        whl_file=input_whl_file.as_posix(),
        dest_dir=tmp_path.as_posix(),
        target_version=output_version,
    )

    assert output_whl_file.is_file() is True

    # Confirm that it can be consumed.
    output_pex_file = tmp_path / "out.pex"
    subprocess.run(
        args=[
            sys.executable,
            "-mpex",
            "--include-tools",
            "--disable-cache",
            "-o",
            str(output_pex_file),
            str(output_whl_file),
        ],
        check=True,
    )
    assert output_pex_file.is_file()

    assert (
        input_version
        == subprocess.run(
            args=[
                sys.executable,
                str(output_pex_file),
                "-c",
                "import colors; print(colors.__version__)",
            ],
            check=True,
            stdout=subprocess.PIPE,
        )
        .stdout.decode()
        .strip()
    ), "Did not expect re-versioning to change the version stored in code."

    info = json.loads(
        subprocess.run(
            args=[sys.executable, str(output_pex_file), "repository", "info", "-v"],
            check=True,
            stdout=subprocess.PIPE,
            env={"PEX_TOOLS": "1", **os.environ},
        ).stdout
    )
    assert "ansicolors" == info["project_name"]
    assert (
        output_version == info["version"]
    ), "Expected re-versioning to change the version stored in wheel metadata."
