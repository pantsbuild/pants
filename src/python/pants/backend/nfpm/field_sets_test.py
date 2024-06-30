# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.nfpm.field_sets import (
    NfpmApkPackageFieldSet,
    NfpmArchlinuxPackageFieldSet,
    NfpmDebPackageFieldSet,
    NfpmRpmPackageFieldSet,
)
from pants.backend.nfpm.fields.all import NfpmHomepageField, NfpmLicenseField, NfpmPackageNameField
from pants.backend.nfpm.fields.apk import NfpmApkDependsField, NfpmApkMaintainerField
from pants.backend.nfpm.fields.archlinux import (
    NfpmArchlinuxDependsField,
    NfpmArchlinuxPackagerField,
)
from pants.backend.nfpm.fields.deb import (
    NfpmDebDependsField,
    NfpmDebFieldsField,
    NfpmDebMaintainerField,
    NfpmDebSectionField,
    NfpmDebTriggersField,
)
from pants.backend.nfpm.fields.rpm import (
    NfpmRpmDependsField,
    NfpmRpmGhostContents,
    NfpmRpmPackagerField,
    NfpmRpmPrefixesField,
)
from pants.backend.nfpm.fields.scripts import NfpmPackageScriptsField
from pants.backend.nfpm.fields.version import NfpmVersionField
from pants.backend.nfpm.target_types import (
    NfpmApkPackage,
    NfpmArchlinuxPackage,
    NfpmDebPackage,
    NfpmRpmPackage,
)
from pants.engine.addresses import Address
from pants.engine.target import DescriptionField


def test_generate_nfpm_config_for_apk():
    depends = [
        "git=2.40.1-r0",
        "/bin/sh",
        "so:libcurl.so.4",
    ]
    tgt = NfpmApkPackage(
        {
            NfpmPackageNameField.alias: "treasure",
            NfpmVersionField.alias: "3.2.1",
            DescriptionField.alias: "Black Beard's buried treasure.",
            NfpmPackageScriptsField.alias: {
                "preinstall": "hornswaggle",
                "preupgrade": "plunder",
            },
            NfpmApkMaintainerField.alias: "Black Beard <bb@jolly.roger.example.com",
            NfpmHomepageField.alias: "https://jolly.roger.example.com",
            NfpmLicenseField.alias: "MIT",
            NfpmApkDependsField.alias: depends,
        },
        Address("", target_name="t"),
    )
    expected_nfpm_config = {
        "disable_globbing": True,
        "contents": [],
        "name": "treasure",
        "arch": "amd64",  # default
        "version": "3.2.1",
        "version_scheme": "semver",  # default
        "release": 1,  # default
        "maintainer": "Black Beard <bb@jolly.roger.example.com",
        "homepage": "https://jolly.roger.example.com",
        "license": "MIT",
        "depends": depends,
        "scripts": {"preinstall": "hornswaggle"},
        "apk": {
            "scripts": {"preupgrade": "plunder"},
        },
        "description": "Black Beard's buried treasure.",
    }

    field_set = NfpmApkPackageFieldSet.create(tgt)
    nfpm_config = field_set.nfpm_config(tgt)
    assert nfpm_config == expected_nfpm_config


def test_generate_nfpm_config_for_archlinux():
    depends = [
        "git",
        "tcpdump<5",
        "foobar>=1.8.0",
    ]
    tgt = NfpmArchlinuxPackage(
        {
            NfpmPackageNameField.alias: "treasure",
            NfpmVersionField.alias: "3.2.1",
            DescriptionField.alias: "Black Beard's buried treasure.",
            NfpmPackageScriptsField.alias: {
                "preinstall": "hornswaggle",
                "preupgrade": "plunder",
            },
            NfpmArchlinuxPackagerField.alias: "Black Beard <bb@jolly.roger.example.com",
            NfpmHomepageField.alias: "https://jolly.roger.example.com",
            NfpmLicenseField.alias: "MIT",
            NfpmArchlinuxDependsField.alias: depends,
        },
        Address("", target_name="t"),
    )
    expected_nfpm_config = {
        "disable_globbing": True,
        "contents": [],
        "name": "treasure",
        "arch": "amd64",  # default
        "version": "3.2.1",
        "version_scheme": "semver",  # default
        "release": 1,  # default
        "homepage": "https://jolly.roger.example.com",
        "license": "MIT",
        "depends": depends,
        "scripts": {"preinstall": "hornswaggle"},
        "archlinux": {
            "packager": "Black Beard <bb@jolly.roger.example.com",
            "scripts": {"preupgrade": "plunder"},
        },
        "description": "Black Beard's buried treasure.",
    }

    field_set = NfpmArchlinuxPackageFieldSet.create(tgt)
    nfpm_config = field_set.nfpm_config(tgt)
    assert nfpm_config == expected_nfpm_config


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
        "name": "treasure",
        "arch": "amd64",  # default
        "version": "3.2.1",
        "version_scheme": "semver",  # default
        "release": 1,  # default
        "priority": "optional",  # default
        "maintainer": "Black Beard <bb@jolly.roger.example.com",
        "homepage": "https://jolly.roger.example.com",
        "license": "MIT",
        "section": "miscellaneous",
        "depends": depends,
        "scripts": {"preinstall": "hornswaggle"},
        "deb": {
            "compression": "gzip",  # default
            "fields": {"Urgency": "high (critical for landlubbers)"},
            "triggers": {"interest_noawait": ["some-trigger", "other-trigger"]},
            "scripts": {"templates": "plunder"},
        },
        "description": "Black Beard's buried treasure.",
    }

    field_set = NfpmDebPackageFieldSet.create(tgt)
    nfpm_config = field_set.nfpm_config(tgt)
    assert nfpm_config == expected_nfpm_config


def test_generate_nfpm_config_for_rpm():
    depends = [
        "git",
        "bash < 5",
        "perl >= 9:5.00502-3",
    ]
    tgt = NfpmRpmPackage(
        {
            NfpmPackageNameField.alias: "treasure",
            NfpmVersionField.alias: "3.2.1",
            DescriptionField.alias: "Black Beard's buried treasure.",
            NfpmPackageScriptsField.alias: {
                "preinstall": "hornswaggle",
                "pretrans": "plunder",
            },
            NfpmRpmPackagerField.alias: "Black Beard <bb@jolly.roger.example.com",
            NfpmHomepageField.alias: "https://jolly.roger.example.com",
            NfpmLicenseField.alias: "MIT",
            NfpmRpmDependsField.alias: depends,
            NfpmRpmPrefixesField.alias: ["/", "/usr", "/opt/treasure"],
            NfpmRpmGhostContents.alias: ["/var/log/captains.log"],
        },
        Address("", target_name="t"),
    )
    expected_nfpm_config = {
        "disable_globbing": True,
        "contents": [
            {"type": "ghost", "dst": "/var/log/captains.log"},
        ],
        "name": "treasure",
        "arch": "amd64",  # default
        "version": "3.2.1",
        "version_scheme": "semver",  # default
        "release": 1,  # default
        "homepage": "https://jolly.roger.example.com",
        "license": "MIT",
        "depends": depends,
        "scripts": {"preinstall": "hornswaggle"},
        "rpm": {
            "compression": "gzip:-1",  # default
            "packager": "Black Beard <bb@jolly.roger.example.com",
            "prefixes": ["/", "/usr", "/opt/treasure"],
            "scripts": {"pretrans": "plunder"},
        },
        "description": "Black Beard's buried treasure.",
    }

    field_set = NfpmRpmPackageFieldSet.create(tgt)
    nfpm_config = field_set.nfpm_config(tgt)
    assert nfpm_config == expected_nfpm_config
