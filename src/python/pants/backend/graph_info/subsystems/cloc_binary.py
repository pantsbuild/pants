# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.binaries.binary_tool import Script, ToolForPlatform, ToolVersion
from pants.engine.fs import Digest
from pants.engine.platform import PlatformConstraint


class ClocBinary(Script):
    # Note: Not in scope 'cloc' because that's the name of the singleton task that runs cloc.
    options_scope = "cloc-binary"
    name = "cloc"
    default_version = "1.80"

    replaces_scope = "cloc"
    replaces_name = "version"

    default_versions_and_digests = {
        PlatformConstraint.none: ToolForPlatform(
            digest=Digest(
                "2b23012b1c3c53bd6b9dd43cd6aa75715eed4feb2cb6db56ac3fbbd2dffeac9d", 546279
            ),
            version=ToolVersion("1.80"),
        ),
    }
