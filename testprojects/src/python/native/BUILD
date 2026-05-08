# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(name="lib", sources=["name.py", "setup.py"])

resources(name="impl", sources=["*.c"])

resources(name="pyproject", sources=["pyproject.toml"])

python_distribution(
    name="dist",
    dependencies=[":pyproject", ":impl", ":lib"],
    generate_setup=False,
    provides=python_artifact(name="native", version="2.3.4"),
    sdist=False,
    wheel_config_settings={"--global-option": ["--python-tag", "py36.py37"]},
)

python_sources(name="main_lib", sources=["main.py"])

pex_binary(
    name="main",
    entry_point="main.py",
    dependencies=[":dist", ":main_lib"],
    interpreter_constraints=["==3.14.*"],
)
