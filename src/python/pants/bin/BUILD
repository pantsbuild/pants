# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(name="tests")

_common_pex_kwargs = dict(
    entry_point="./pants_loader:main",
    strip_pex_env=False,
    execution_mode="venv",
)

pex_binary(name="pants-local-pex", **common_pex_kwargs)

pex_binary(
    name="pants-release-pex",
    **_common_pex_kwargs,
    shebang="/usr/bin/env python",
    platforms=[
        "linux_x86_64_cp-37-cp37m",
        "linux_x86_64_cp-38-cp38",
        "linux_x86_64_cp-39-cp39",
        "macosx_10.15_cp-37-cp37m",
        "macosx_10.15_cp-38-cp38",
        "macosx_10.15_cp-39-cp39",
    ],
)
