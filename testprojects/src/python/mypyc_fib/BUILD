# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(name="lib", sources=["setup.py", "mypyc_fib/*.py"])

resources(name="pyproject", sources=["pyproject.toml"])

python_distribution(
    name="dist",
    dependencies=[":pyproject", ":lib"],
    generate_setup=False,
    provides=python_artifact(name="mypyc_fib", version="2.3.4"),
    sdist=False,
    uses_mypyc=True,
)
