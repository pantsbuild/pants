# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


import shutil
from pathlib import Path

import requests
from pex.bin import pex as pex_main
from reversion import reversion


def test_reversion(tmp_path: Path) -> None:
    # Download an input whl.
    name_template = "virtualenv-{}-py2.py3-none-any.whl"
    input_name = name_template.format("15.1.0")
    url = (
        "https://files.pythonhosted.org/packages/6f/86/"
        "3dc328ee7b1a6419ebfac7896d882fba83c48e3561d22ddddf38294d3e83/{}".format(input_name)
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
    pex_main.main(["--disable-cache", "-o", output_pex_file.as_posix(), output_whl_file.as_posix()])
    assert output_pex_file.is_file() is True
