# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.javascript.package_json import PackageJsonEntryPoints
from pants.core.util_rules.unowned_dependency_behavior import UnownedDependencyUsageOption
from pants.option.option_types import BoolOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


class NodeJSInfer(Subsystem):
    options_scope = "nodejs-infer"
    help = "Options controlling which dependencies will be inferred for javascript targets."

    imports = BoolOption(
        default=True,
        help=softwrap(
            """
            Infer a target's imported dependencies by parsing import statements from sources.

            To ignore a false positive, you can either put `// pants: no-infer-dep` on the line of
            the import or put `!{bad_address}` in the `dependencies` field of your target.
            """
        ),
    )

    package_json_entry_points = BoolOption(
        default=True,
        help=softwrap(
            f"""
            Infer a `package_json`'s dependencies by parsing entry point statements from the package.json file.

            To ignore a false positive, you can put `!{{bad_address}}` in the `dependencies` field of the `package_json`
            target.

            {PackageJsonEntryPoints.__doc__}
            """
        ),
    )
    unowned_dependency_behavior = UnownedDependencyUsageOption(
        example_runtime_issue="`Error: ENOENT: no such file or directory`",
        how_to_ignore="add `// pants: no-infer-dep` to the line of the import",
    )
