# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# these _SCRIPTS should be both python_sources and resources
_SCRIPTS = ("analyze",)
__dependents_rules__(
    (
        # the python targets of these scripts
        tuple(f"<python_source*>[/{script}.py]" for script in _SCRIPTS),
        # can be dependencies of these scripts and script tests
        tuple(f"<python_*>[/{script}*.py]" for script in _SCRIPTS),
        # and nothing else
        "!*",
    ),
    # fall back to parent rulesets in //src/python/pants/backend/BUILD
    extend=True,
)

resources(name="lockfile", sources=["elfdeps.lock*"])
resources(name="scripts", sources=[f"{script}.py" for script in _SCRIPTS])

python_sources(
    overrides={"subsystem.py": dict(dependencies=[":lockfile", ":scripts"])},
)

python_tests(
    name="tests",
)
