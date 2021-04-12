# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.engine.rules import collect_rules


class GoLangDistribution(TemplatedExternalTool):
    options_scope = "golang"
    name = "golang"
    help = "Official golang distribution."

    default_version = "1.15.5"
    default_known_versions = [
        "1.15.5|darwin|359a4334b8c8f5e3067e5a76f16419791ac3fef4613d8e8e1eac0b9719915f6d|122217003",
        "1.15.5|linux |9a58494e8da722c3aef248c9227b0e9c528c7318309827780f16220998180a0d|120900442",
    ]
    default_url_template = "https://golang.org/dl/go{version}.{platform}-amd64.tar.gz"
    default_url_platform_mapping = {
        "darwin": "darwin",
        "linux": "linux",
    }

    def generate_exe(self, plat: Platform) -> str:
        return "./bin"


def rules():
    return collect_rules()
