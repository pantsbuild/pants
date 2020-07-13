# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

# NB: In this example project, we import a module added via `setup_requires` in our BUILD file, and
# make some modifications to the `setup.py` project. These get picked up and tested in
# `test_setup_requires.py`.
from checksumdir import dirhash
from setuptools import find_packages, setup

this_dir_hash = dirhash(".", "sha256")

checksum_module_dir = Path("checksum")
checksum_module_dir.mkdir()
checksum_module_dir.joinpath("__init__.py").write_text(
    f"""\
checksum = '{this_dir_hash}'
"""
)

setup(
    name="checksummed_version_dist", version="0.0.1", packages=find_packages(),
)
