# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import cast

from pants.backend.javascript.package_json import PackageJsonTarget
from pants.core.goals.test import Test
from pants.core.target_types import FileTarget
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem
from pants.util.docutil import bin_name
from pants.util.strutil import help_text

_EXAMPLE = """\
Consider a directory-layout:

├── BUILD
├── src/
│   ├── BUILD
│   ├── test/
│   │   ├── BUILD
│   │   └── index.test.js
│   └── index.js
└── package.json

where package.json contains

# package.json
{
    ...
    "scripts": {
        "test": "mocha"
    },
    "devDependencies: {
        ...
    }
}
"""


class NodeJSTest(Subsystem):
    options_scope = "nodejs-test"
    help = cast(
        str,
        help_text(
            f"""
        Options for package.json scripts configured tests.

        Your preferred test runner is configured via the `package.json#scripts.test`
        field.

        The only expectation from pants is that the `test` script can
        accept a variadic number of path arguments, relative to the package.json,
        and that any configuration files are `{FileTarget.alias}` dependencies
        to the `{PackageJsonTarget.alias}`.

        Simple example:

        {{}}

        Executing `{bin_name()} {Test.name} src/test/index.test.js`
        will cause the equivalent of `mocha src/test/index.test.js` to run.
        """
        ),
    ).format(_EXAMPLE)
    name = "Node.js tests"

    skip = SkipOption("test")
