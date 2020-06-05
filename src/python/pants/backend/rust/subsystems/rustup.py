# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.util_rules.external_tool import ExternalTool
from pants.engine.platform import Platform
from pants.engine.rules import rule


class Rustup(ExternalTool):
    """A tool to download rustup-init.sh

    NB: This tool is versioned by its checksum, not by a semver string.
    """
    options_scope = 'rustup'
    default_version = '79552216b4ccab5f773a981bc156b38b004a4f94ac5d2b83f8e127020a4d0bfe'
    default_known_versions = [
        f"{default_version}|{plat}|{default_version}|11325"
        for plat in ['darwin', 'linux']
    ]

    def generate_url(self, _plat: Platform) -> str:
        return 'https://sh.rustup.rs'
