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

python_requirement(
    name="setuptools-scm",
    requirements=[
        # NB: Keep in sync with 3rdparty/python/pants_dev_requirements.txt until we use off-the-shelf
        "setuptools_scm @ git+https://github.com/pypa/setuptools_scm.git@a23d5fe61d9dc421666d5f23334d454426ad311c"
    ],
    resolve="setuptools-scm",
)

python_requirements(
    name="pytest",
    source="pytest-requirements.txt",
    resolve="pytest",
)

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
