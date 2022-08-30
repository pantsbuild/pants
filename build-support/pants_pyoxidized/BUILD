# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


# EXPERIMENTAL ONLY

pyoxidizer_binary(
    name="pants_pyoxidized_experimental",
    binary_name="pants",
    dependencies=["src/python/pants:pants-packaged"],
    output_path="pants",
    entry_point="pants.bin.pants_loader",
)

archive(
    description="Archive containing self-contained binary of Pants and its dynamic libraries",
    name="pants_pyoxidized_distribution_experimental",
    packages=[":pants_pyoxidized_experimental"],
    format="zip",
)
