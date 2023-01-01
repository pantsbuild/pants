# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.python.goals.package_pex_binary import PexBinaryFieldSet
from pants.backend.python.target_types import PexLayout
from pants.core.goals.package import BuiltPackage
from pants.core.goals.run import RunRequest
from pants.engine.rules import Get, collect_rules, rule
from pants.util.logging import LogLevel


@rule(level=LogLevel.DEBUG)
async def create_pex_binary_run_request(field_set: PexBinaryFieldSet) -> RunRequest:
    built_pex = await Get(BuiltPackage, PexBinaryFieldSet, field_set)
    relpath = built_pex.artifacts[0].relpath
    assert relpath is not None
    if field_set.layout.value != PexLayout.ZIPAPP.value:
        relpath = os.path.join(relpath, "__main__.py")

    return RunRequest(
        digest=built_pex.digest,
        args=[os.path.join("{chroot}", relpath)],
    )


# NB: Technically we could implement RunDebugAdapterRequest by using `debugpy`.
# However it is unclear how the user would be able to debug the code,
# as the client and server will disagree on the code's path.


def rules():
    return [
        *collect_rules(),
        *PexBinaryFieldSet.rules(),
    ]
