# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.nfpm.field_sets import NfpmPackageFieldSet
from pants.backend.nfpm.target_types import NfpmContentDir, NfpmContentFile, NfpmContentSymlink
from pants.backend.nfpm.util_rules.sandbox import _DepCategory
from pants.core.target_types import ArchiveTarget, FileTarget, GenericTarget, ResourceTarget
from pants.engine.addresses import Address
from pants.engine.target import Target

# _NfpmSortedDeps.sort(...)

_A = Address("", target_name="t")


@pytest.mark.parametrize(
    "tgt,field_set_type,expected",
    (
        (NfpmContentDir({"dst": "/foo"}, _A), NfpmPackageFieldSet, _DepCategory.ignore),
        (
            NfpmContentSymlink({"dst": "/foo", "src": "/bar"}, _A),
            NfpmPackageFieldSet,  # does not matter
            _DepCategory.ignore,
        ),
        (
            NfpmContentFile({"dst": "/foo", "src": "bar", "dependencies": [":bar"]}, _A),
            NfpmPackageFieldSet,  # does not matter
            _DepCategory.nfpm_content_from_dependency,
        ),
        (
            NfpmContentFile({"dst": "/foo", "source": "bar"}, _A),
            NfpmPackageFieldSet,  # does not matter
            _DepCategory.nfpm_content_from_source,
        ),
        (GenericTarget({}, _A), NfpmPackageFieldSet, _DepCategory.remaining),
        (FileTarget({"source": "foo"}, _A), NfpmPackageFieldSet, _DepCategory.remaining),
        (ResourceTarget({"source": "foo"}, _A), NfpmPackageFieldSet, _DepCategory.remaining),
        (ArchiveTarget({"format": "zip"}, _A), NfpmPackageFieldSet, _DepCategory.remaining),
    ),
)
def test_dep_category_for_target(
    tgt: Target, field_set_type: type[NfpmPackageFieldSet], expected: _DepCategory
):
    category = _DepCategory.for_target(tgt, field_set_type)
    assert category == expected
