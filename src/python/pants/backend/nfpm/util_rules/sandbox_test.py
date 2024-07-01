# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Type

import pytest

from pants.backend.nfpm.field_sets import (
    NfpmApkPackageFieldSet,
    NfpmArchlinuxPackageFieldSet,
    NfpmDebPackageFieldSet,
    NfpmPackageFieldSet,
    NfpmRpmPackageFieldSet,
)
from pants.backend.nfpm.target_types import (
    NfpmApkPackage,
    NfpmArchlinuxPackage,
    NfpmContentDir,
    NfpmContentFile,
    NfpmContentSymlink,
    NfpmDebPackage,
    NfpmRpmPackage,
)
from pants.backend.nfpm.util_rules.sandbox import _DepCategory
from pants.core.target_types import ArchiveTarget, FileTarget, GenericTarget, ResourceTarget
from pants.engine.addresses import Address
from pants.engine.target import Target

# _NfpmSortedDeps.sort(...)

_a = Address("", target_name="t")
_apk_pkg = NfpmApkPackage({"package_name": "pkg", "version": "3.2.1"}, _a)
_archlinux_pkg = NfpmArchlinuxPackage({"package_name": "pkg", "version": "3.2.1"}, _a)
_deb_pkg = NfpmDebPackage(
    {"package_name": "pkg", "version": "3.2.1", "maintainer": "Foo Bar <baz@example.com>"}, _a
)
_rpm_pkg = NfpmRpmPackage({"package_name": "pkg", "version": "3.2.1"}, _a)


@pytest.mark.parametrize(
    "tgt,field_set_type,expected",
    (
        (NfpmContentDir({"dst": "/foo"}, _a), NfpmPackageFieldSet, _DepCategory.ignore),
        (
            NfpmContentSymlink({"dst": "/foo", "src": "/bar"}, _a),
            NfpmPackageFieldSet,  # does not matter
            _DepCategory.ignore,
        ),
        (
            NfpmContentFile({"dst": "/foo", "src": "bar", "dependencies": [":bar"]}, _a),
            NfpmPackageFieldSet,  # does not matter
            _DepCategory.nfpm_content_from_dependency,
        ),
        (
            NfpmContentFile({"dst": "/foo", "source": "bar"}, _a),
            NfpmPackageFieldSet,  # does not matter
            _DepCategory.nfpm_content_from_source,
        ),
        (_apk_pkg, NfpmApkPackageFieldSet, _DepCategory.nfpm_package),
        (_apk_pkg, NfpmArchlinuxPackageFieldSet, _DepCategory.ignore),
        (_apk_pkg, NfpmDebPackageFieldSet, _DepCategory.ignore),
        (_apk_pkg, NfpmRpmPackageFieldSet, _DepCategory.ignore),
        (_archlinux_pkg, NfpmApkPackageFieldSet, _DepCategory.ignore),
        (_archlinux_pkg, NfpmArchlinuxPackageFieldSet, _DepCategory.nfpm_package),
        (_archlinux_pkg, NfpmDebPackageFieldSet, _DepCategory.ignore),
        (_archlinux_pkg, NfpmRpmPackageFieldSet, _DepCategory.ignore),
        (_deb_pkg, NfpmApkPackageFieldSet, _DepCategory.ignore),
        (_deb_pkg, NfpmArchlinuxPackageFieldSet, _DepCategory.ignore),
        (_deb_pkg, NfpmDebPackageFieldSet, _DepCategory.nfpm_package),
        (_deb_pkg, NfpmRpmPackageFieldSet, _DepCategory.ignore),
        (_rpm_pkg, NfpmApkPackageFieldSet, _DepCategory.ignore),
        (_rpm_pkg, NfpmArchlinuxPackageFieldSet, _DepCategory.ignore),
        (_rpm_pkg, NfpmDebPackageFieldSet, _DepCategory.ignore),
        (_rpm_pkg, NfpmRpmPackageFieldSet, _DepCategory.nfpm_package),
        (GenericTarget({}, _a), NfpmPackageFieldSet, _DepCategory.remaining),
        (FileTarget({"source": "foo"}, _a), NfpmPackageFieldSet, _DepCategory.remaining),
        (ResourceTarget({"source": "foo"}, _a), NfpmPackageFieldSet, _DepCategory.remaining),
        (ArchiveTarget({"format": "zip"}, _a), NfpmPackageFieldSet, _DepCategory.remaining),
    ),
)
def test_dep_category_for_target(
    tgt: Target, field_set_type: Type[NfpmPackageFieldSet], expected: _DepCategory
):
    category = _DepCategory.for_target(tgt, field_set_type)
    assert category == expected
