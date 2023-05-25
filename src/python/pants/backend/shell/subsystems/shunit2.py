# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.util_rules import external_tool
from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.rules import collect_rules
from pants.option.option_types import SkipOption
from pants.util.meta import classproperty


class Shunit2(TemplatedExternalTool):
    options_scope = "shunit2"
    name = "shunit2"
    help = "shUnit2 is a xUnit framework for Bourne based shell scripts (https://github.com/kward/shunit2)"

    # shUnit2 almost never cuts "official" releases, so we point directly at git SHAs.
    default_version = "b9102bb763cc603b3115ed30a5648bf950548097"
    default_url_template = "https://raw.githubusercontent.com/kward/shunit2/{version}/shunit2"

    skip = SkipOption("test")

    @classproperty
    def default_known_versions(cls):
        return [
            "|".join(
                (
                    cls.default_version,
                    plat,
                    "1f11477b7948150d1ca50cdd41d89be4ed2acd137e26d2e0fe23966d0e272cc5",
                    "40987",
                )
            )
            for plat in ["macos_arm64", "macos_x86_64", "linux_x86_64", "linux_arm64"]
        ]


def rules():
    return [
        *collect_rules(),
        *external_tool.rules(),
    ]
