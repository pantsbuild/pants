# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_requirements(
    module_mapping={
        "strawberry-graphql": ["strawberry"],
        "beautifulsoup4": ["bs4"],
        "python-gnupg": ["gnupg"],
        "node-semver": ["nodesemver"],
    },
)

python_requirements(
    name="flake8",
    source="flake8-requirements.txt",
    resolve="flake8",
)

python_requirements(
    name="mypy",
    source="mypy-requirements.txt",
    resolve="mypy",
)

python_requirements(
    name="pytest",
    source="pytest-requirements.txt",
    resolve="pytest",
)

# Useful when using IntelliJ/PyCharm remote debugging. Importing `pydevd_pycharm` at
# the breakpoint will cause dep inference to add this dep on the remote debugger client.
python_requirement(name="pydevd-pycharm", requirements=["pydevd-pycharm==203.5419.8"])


__dependents_rules__(
    (  # Only the explorer server may depend on these libraries
        (
            "[fastapi]",
            "[starlette]",
            "[strawberry-graphql]",
            "[uvicorn]",
        ),
        "pants-plugins/pants_explorer/server/**",
        "!*",
    ),
    # Free for all on the rest
    ("*", "*"),
)
