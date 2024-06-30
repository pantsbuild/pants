# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.nfpm.fields.contents import (
    NfpmContentDstField,
    NfpmContentFileSourceField,
    NfpmContentSrcField,
    NfpmDependencies,
)
from pants.backend.nfpm.target_types import NfpmContentFile
from pants.engine.addresses import Address
from pants.engine.target import InvalidTargetException


def test_nfpm_content_file_validate() -> None:
    def create_tgt(
        *, source: str | None, src: str | None, dependencies: list[str]
    ) -> NfpmContentFile:
        return NfpmContentFile(
            {
                NfpmContentFileSourceField.alias: source,
                NfpmContentSrcField.alias: src,
                NfpmDependencies.alias: dependencies,
                # dst is always required
                NfpmContentDstField.alias: "/opt/destination",
            },
            Address("", target_name="t"),
        )

    # target requires one of:
    # - source, src, optional dependencies
    # - source, !src, optional dependencies
    # - !source, src, dependencies

    create_tgt(source="workspace.file", src="relocated.file", dependencies=["foo"])
    create_tgt(source="workspace.file", src="relocated.file", dependencies=[])
    create_tgt(source="workspace.file", src=None, dependencies=["foo"])
    create_tgt(source="workspace.file", src=None, dependencies=[])
    create_tgt(source=None, src="dep-foo.file", dependencies=["foo"])

    with pytest.raises(InvalidTargetException):
        create_tgt(source=None, src="some.file", dependencies=[])
