# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil

import requests
from pex.bin import pex as pex_main
from reversion import reversion

from pants.util.contextutil import temporary_dir


def test_reversion() -> None:
    with temporary_dir() as dest_dir:
        # Download an input whl.
        name_template = "virtualenv-{}-py2.py3-none-any.whl"
        input_name = name_template.format("15.1.0")
        url = (
            "https://files.pythonhosted.org/packages/6f/86/"
            "3dc328ee7b1a6419ebfac7896d882fba83c48e3561d22ddddf38294d3e83/{}".format(input_name)
        )
        input_whl_file = os.path.join(dest_dir, input_name)
        with open(input_whl_file, "wb") as f:
            shutil.copyfileobj(requests.get(url, stream=True).raw, f)

        # Rewrite it.
        output_version = "9.1.9"
        output_name = name_template.format(output_version)
        output_whl_file = os.path.join(dest_dir, output_name)

        reversion(whl_file=input_whl_file, dest_dir=dest_dir, target_version=output_version)

        assert os.path.isfile(output_whl_file) is True

        # Confirm that it can be consumed.
        output_pex_file = os.path.join(dest_dir, "out.pex")
        pex_main.main(["--disable-cache", "-o", output_pex_file, output_whl_file])
        assert os.path.isfile(output_pex_file) is True
