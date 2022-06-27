# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import inspect
import json
import sys
from pathlib import Path

import pytest
from _pytest import fixtures
from _pytest.compat import get_real_func


def get_func_path(func):
    real_func = get_real_func(func)
    return inspect.getfile(real_func)


def get_fixturedef(fixture_request, name):
    fixturedef = fixture_request._fixture_defs.get(name)
    if fixturedef:
        return fixturedef
    try:
        return fixture_request._getnextfixturedef(name)
    except fixtures.FixtureLookupError:
        return None


def process_fixtures(item):
    lockfile_definitions = []
    fixture_request = fixtures.FixtureRequest(item, _ispytest=True)
    for fixture_name in fixture_request.fixturenames:
        fixture_def = get_fixturedef(fixture_request, fixture_name)
        if not fixture_def:
            continue

        func = fixture_def.func
        annotations = getattr(func, "__annotations__")
        if not annotations or annotations.get("return") != "JVMLockfileFixtureDefinition":
            continue

        # Note: We just invoke the fixture_def function assuming it takes no arguments. The other two
        # ways of invoking for the fixture value cause errors. I have left them here commented-out as an example
        # of what failed:
        #   lockfile_definition = fixture_request.getfixturevalue(fixture_name)
        #   lockfile_definition = fixture_def.execute(request=request)
        try:
            lockfile_definition = func()
        except Exception as err:
            raise ValueError(
                f"Exception while getting lockfile definition (file {item.path}): {err}"
            )
        if lockfile_definition.__class__.__name__ != "JVMLockfileFixtureDefinition":
            continue

        cwd = Path.cwd()
        func_path = Path(get_func_path(func)).relative_to(cwd)
        lockfile_definitions.append(
            {
                "lockfile_rel_path": str(lockfile_definition.lockfile_rel_path),
                "requirements": [c.to_coord_str() for c in lockfile_definition.requirements],
                "test_file_path": str(func_path),
            }
        )
    return lockfile_definitions


class CollectionPlugin:
    def __init__(self):
        self.collected = []

    def pytest_collection_modifyitems(self, items):
        for item in items:
            self.collected.append(item)


collection_plugin = CollectionPlugin()
pytest.main(["--setup-only", *sys.argv[1:]], plugins=[collection_plugin])

output = []
cwd = Path.cwd()

for item in collection_plugin.collected:
    output.extend(process_fixtures(item))

with open("tests.json", "w") as f:
    f.write(json.dumps(output))
