# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.util_rules.external_tool import ExternalTool
from pants.engine.platform import Platform


class LLVM(ExternalTool):
    """Subsystem wrapping an archive providing an LLVM distribution.

    This subsystem provides the clang and clang++ compilers. It also provides lld, which is not
    currently used.

    NB: The lib and include dirs provided by this distribution are produced by using known relative
    paths into the distribution of LLVM from LLVMReleaseUrlGenerator. If LLVM changes the structure of
    their release archives, these methods may have to change. They should be stable to version
    upgrades, however.
    """

    options_scope = "llvm"
    default_version = "6.0.0"
    default_known_versions = [
        "6.0.0|darwin|0ef8e99e9c9b262a53ab8f2821e2391d041615dd3f3ff36fdf5370916b0f4268|290272140",
        "6.0.0|linux |cc99fda45b4c740f35d0a367985a2bf55491065a501e2dd5d1ad3f97dcac89da|292373416",
    ]

    def generate_url(self, plat: Platform) -> str:
        system_id = "apple-darwin" if plat == Platform.darwin else "linux-gnu-ubuntu-16.04"
        archive_basename = f"clang+llvm-{self.options.version}-x86_64-{system_id}"
        return f"https://releases.llvm.org/{self.options.version}/{archive_basename}.tar.xz"
