# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform
from pants.engine.rules import collect_rules


class GoLangDistribution(TemplatedExternalTool):
    options_scope = "golang"
    name = "golang"
    help = "Official golang distribution."

    default_version = "1.16.5"
    default_known_versions = [
        "1.16.5|macos_arm64 |7b1bed9b63d69f1caa14a8d6911fbd743e8c37e21ed4e5b5afdbbaa80d070059|125731583",
        "1.16.5|macos_x86_64|be761716d5bfc958a5367440f68ba6563509da2f539ad1e1864bd42fe553f277|130223787",
        "1.16.5|linux_x86_64|b12c23023b68de22f74c0524f10b753e7b08b1504cb7e417eccebdd3fae49061|129049763",
    ]
    default_url_template = "https://golang.org/dl/go{version}.{platform}.tar.gz"
    default_url_platform_mapping = {
        "macos_arm64": "darwin-arm64",
        "macos_x86_64": "darwin-amd64",
        "linux_x86_64": "linux-amd64",
    }

    def generate_exe(self, plat: Platform) -> str:
        return "./bin"


def rules():
    return collect_rules()
