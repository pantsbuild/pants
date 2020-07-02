# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.util_rules.external_tool import ExternalTool
from pants.engine.platform import Platform


class GCC(ExternalTool):
    """Subsystem wrapping an archive providing a GCC distribution.

    This subsystem provides the gcc and g++ compilers.

    NB: The lib and include dirs provided by this distribution are produced by using known relative
    paths into the distribution of GCC provided on Pantsbuild S3. If we change how we distribute GCC,
    these methods may have to change. They should be stable to version upgrades, however.
    """

    options_scope = "gcc"
    default_version = "7.3.0"

    default_known_versions = [
        "7.3.0|darwin|c3245e0c56bb13007312f0d0b4ee76fd0b62abe1740e840e1618b0a312aeb628|53193089",
        "7.3.0|linux |fa144939d06f3277b1fc72d2b3a0e62b3ed6f59563efcb5e58e65eab704caef7|253056372",
    ]

    def generate_url(self, plat: Platform) -> str:
        plat_str = "mac/10.13" if plat == Platform.darwin else "linux/x86_64"
        return (
            f"https://binaries.pantsbuild.org/bin/gcc/{plat_str}/{self.options.version}/gcc.tar.gz"
        )
