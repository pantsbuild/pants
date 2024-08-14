# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.nfpm.field_sets import NfpmDebPackageFieldSet
from pants.backend.nfpm.fields.all import (
    NfpmHomepageField,
    NfpmLicenseField,
    NfpmPackageMtimeField,
    NfpmPackageNameField,
)
from pants.backend.nfpm.fields.deb import (
    NfpmDebDependsField,
    NfpmDebFieldsField,
    NfpmDebMaintainerField,
    NfpmDebSectionField,
    NfpmDebTriggersField,
)
from pants.backend.nfpm.fields.scripts import NfpmPackageScriptsField
from pants.backend.nfpm.fields.version import NfpmVersionField
from pants.backend.nfpm.target_types import NfpmDebPackage
from pants.engine.addresses import Address
from pants.engine.target import DescriptionField

MTIME = NfpmPackageMtimeField.default


def test_generate_nfpm_config_for_deb():
    depends = [
        "git",
        "libc6 (>= 2.2.1)",
        "default-mta | mail-transport-agent",
    ]
    tgt = NfpmDebPackage(
        {
            NfpmPackageNameField.alias: "treasure",
            NfpmVersionField.alias: "3.2.1",
            DescriptionField.alias: "Black Beard's buried treasure.",
            NfpmPackageScriptsField.alias: {
                "preinstall": "hornswaggle",
                "templates": "plunder",
            },
            NfpmDebMaintainerField.alias: "Black Beard <bb@jolly.roger.example.com",
            NfpmHomepageField.alias: "https://jolly.roger.example.com",
            NfpmDebSectionField.alias: "miscellaneous",
            NfpmLicenseField.alias: "MIT",
            NfpmDebDependsField.alias: depends,
            NfpmDebFieldsField.alias: {"Urgency": "high (critical for landlubbers)"},
            NfpmDebTriggersField.alias: {"interest_noawait": ["some-trigger", "other-trigger"]},
        },
        Address("", target_name="t"),
    )
    expected_nfpm_config = {
        "disable_globbing": True,
        "contents": [],
        "mtime": MTIME,
        "name": "treasure",
        "arch": "amd64",  # default
        "platform": "linux",  # default
        "version": "3.2.1",
        "version_schema": "semver",  # default
        "release": 1,  # default
        "priority": "optional",  # default
        "maintainer": "Black Beard <bb@jolly.roger.example.com",
        "homepage": "https://jolly.roger.example.com",
        "license": "MIT",
        "section": "miscellaneous",
        "depends": tuple(depends),
        "scripts": {"preinstall": "hornswaggle"},
        "deb": {
            "compression": "gzip",  # default
            "fields": {"Urgency": "high (critical for landlubbers)"},
            "triggers": {"interest_noawait": ("some-trigger", "other-trigger")},
            "scripts": {"templates": "plunder"},
        },
        "description": "Black Beard's buried treasure.",
    }

    field_set = NfpmDebPackageFieldSet.create(tgt)
    nfpm_config = field_set.nfpm_config(tgt, default_mtime=MTIME)
    assert nfpm_config == expected_nfpm_config
