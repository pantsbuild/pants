# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import importlib

import toml


def test_this_repo_only_uses_baked_backends_or_internal():
    """Test that the backends declared in this repo are solely either:

    - baked into Pants
    - don't use the "pants." prefix

    Put another way, we should be able to run `scie-pants` on this repo without the delegation
    to `./pants`.
    """
    pants_toml = toml.load("pants.toml")
    for package in pants_toml["GLOBAL"]["backend_packages"]["add"]:
        if package.startswith("pants."):
            importlib.import_module(package + ".register")
