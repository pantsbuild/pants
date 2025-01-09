# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(resolve="pbs-script")

pex_binary(
    name="bin",
    entry_point="generate_urls.py",
    dependencies=[":scripts"],
    resolve="pbs-script",
)
