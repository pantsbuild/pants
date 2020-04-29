# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.util_rules.external_tool import ExternalTool
from pants.engine.platform import Platform


class ClocBinary(ExternalTool):
    # Note: Not in scope 'cloc' because that's the name of the singleton task that runs cloc.
    options_scope = "cloc-binary"
    name = "cloc"
    default_version = "1.80"
    default_known_versions = [
        "1.80|darwin|2b23012b1c3c53bd6b9dd43cd6aa75715eed4feb2cb6db56ac3fbbd2dffeac9d|546279",
        "1.80|linux |2b23012b1c3c53bd6b9dd43cd6aa75715eed4feb2cb6db56ac3fbbd2dffeac9d|546279",
    ]

    def generate_url(self, plat: Platform) -> str:
        version = self.get_options().version
        return f"https://github.com/AlDanial/cloc/releases/download/{version}/cloc-{version}.pl"
