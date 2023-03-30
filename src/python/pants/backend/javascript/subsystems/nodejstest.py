# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from pathlib import PurePath
from typing import cast

from pants.backend.javascript.package_json import PackageJsonTarget
from pants.build_graph.address import Address
from pants.core.goals.test import Test
from pants.core.target_types import FileTarget
from pants.core.util_rules.distdir import DistDir
from pants.option.option_types import SkipOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.docutil import bin_name
from pants.util.strutil import help_text, softwrap

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
        Options for package.json script configured tests.

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

    coverage_output_dir = StrOption(
        default=str(PurePath("{distdir}", "coverage", "js", "{target_spec}")),
        advanced=True,
        help=softwrap(
            """
            Path to write the NodeJS coverage reports to. Must be relative to the build root.

            Replacements:

            - `{distdir}` is replaced with the Pants `distdir`.

            - `{target_spec}` is replaced with the address of the applicable `javascript_test` target with `/`
            characters replaced with dots (`.`).
            """
        ),
    )

    def render_coverage_output_dir(self, distdir: DistDir, address: Address) -> PurePath:
        target_spec = address.spec_path.replace(os.sep, ".")
        return PurePath(
            self.coverage_output_dir.format(distdir=distdir.relpath, target_spec=target_spec)
        )
