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

python_requirements(
    name="pbs-script",
    source="pbs-script-requirements.txt",
    resolve="pbs-script",
)

python_requirements(
    name="external-tool-upgrade",
    source="external-tool-upgrade-requirements.txt",
    resolve="external-tool-upgrade",
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
    (  # Only scripts, not including rule code, in the elfdeps backend may depend on the elfdeps library
        ("[elfdeps]",),
        "!src/python/pants/backend/nfpm/native_libs/elfdeps/rules*.py",
        "!src/python/pants/backend/nfpm/native_libs/elfdeps/subsystem.py",
        "src/python/pants/backend/nfpm/native_libs/elfdeps/**",
        "!*",
    ),
    # Free for all on the rest
    ("*", "*"),
)
