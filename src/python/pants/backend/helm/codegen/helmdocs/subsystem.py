# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.engine.platform import Platform


class HelmDocsSubsystem(TemplatedExternalTool):
    options_scope = "helm-docs"
    help = "Helm Chart Documentation Generator (https://github.com/norwoodj/helm-docs)"

    default_version = "1.7.0"
    default_known_versions = [
        "1.7.0|linux_arm64 |8e99abd3c773d46bbfcbeb33d2a857b6a09a1e258ac205acf27bfcc46bdb5895|2291509",
        "1.7.0|linux_x86_64|b39ad34acd03256317692e5c671847d6f12bcd6c92adf05b3df83363d1dac20f|2488622",
        "1.7.0|macos_arm64 |51ce168e3af2dfde5ccbeafd277d9c77cf004544759882b5e3438448d84d6e89|2528267",
        "1.7.0|macos_x86_64|e34b4918ad92c6e553130029895aefc76a353f6ea7d968bbdf8037305dd22313|2579694",
    ]
    default_url_template = "https://github.com/norwoodj/helm-docs/releases/download/v{version}/helm-docs_{version}_{platform}.tar.gz"
    default_url_platform_mapping = {
        "linux_arm64": "Linux_arm64",
        "linux_x86_64": "Linux_x86_64",
        "macos_arm64": "Darwin_arm64",
        "macos_x86_64": "Darwin_x86_64",
    }

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

    def generate_exe(self, _: Platform):
        return "./helm-docs"
