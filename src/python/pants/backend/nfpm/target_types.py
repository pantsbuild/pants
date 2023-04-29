# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum
from typing import ClassVar

from typing_extensions import Protocol

from pants.backend.nfpm.fields.apk import NfpmApkMaintainerField
from pants.backend.nfpm.fields.archlinux import (
    NfpmArchlinuxPackagerField,
    NfpmArchlinuxPkgbaseField,
)
from pants.backend.nfpm.fields.deb import (
    NfpmDebMaintainerField,
    NfpmDebPriorityField,
    NfpmDebSectionField,
)
from pants.backend.nfpm.fields.rpm import (
    NfpmRpmGroupField,
    NfpmRpmPackagerField,
    NfpmRpmSummaryField,
    NfpmRpmVendorField,
)
from pants.backend.nfpm.fields.version import (
    NfpmVersionEpochField,
    NfpmVersionField,
    NfpmVersionMetadataField,
    NfpmVersionPrereleaseField,
    NfpmVersionReleaseField,
    NfpmVersionSchemaField,
)
from pants.core.goals.package import OutputPathField
from pants.engine.target import COMMON_TARGET_FIELDS, StringField, Target
from pants.util.docutil import doc_url
from pants.util.strutil import help_text


# This allows us to define the nFPM config option name on the field
class _NfpmField(Protocol):
    # nfpm_alias is a "." concatenated series of dict keys (keys of nfpm.yaml).
    nfpm_alias: ClassVar[str]


class NfpmPackageNameField(StringField):
    nfpm_alias: str = "name"
    alias = "package_name"
    required = True
    help = help_text(
        """
        The package name.
        """
    )


class GoArch(Enum):
    # GOARCH possible values come from `okgoarch` var at:
    # https://github.com/golang/go/blob/go1.20.3/src/cmd/dist/build.go#L62-L79
    _386 = "386"
    amd64 = "amd64"
    arm = "arm"
    arm64 = "arm64"
    loong64 = "loong64"
    mips = "mips"
    mipsle = "mipsle"
    mips64 = "mips64"
    mips64le = "mips64le"
    ppc64 = "ppc64"
    ppc64le = "ppc64le"
    riscv64 = "riscv64"
    s390x = "s390x"
    sparc64 = "sparc64"
    wasm = "wasm"


class GoOS(Enum):
    # GOOS possible values come from `okgoos` var at:
    # https://github.com/golang/go/blob/go1.20.3/src/cmd/dist/build.go#L81-L98
    # TODO: maybe filter this down to only what nFPM can handle
    darwin = "darwin"
    dragonfly = "dragonfly"
    illumos = "illumos"
    ios = "ios"
    js = "js"
    linux = "linux"
    android = "android"
    solaris = "solaris"
    freebsd = "freebsd"
    nacl = "nacl"
    netbsd = "netbsd"
    openbsd = "openbsd"
    plan9 = "plan9"
    windows = "windows"
    aix = "aix"


class NfpmArchField(StringField):
    nfpm_alias = "arch"
    alias = nfpm_alias
    default = GoArch.amd64.value  # based on nFPM default
    help = help_text(
        """
        The package architecture.

        This should be a valid GOARCH value that nFPM can translate
        into the package-specific equivalent. Otherwise, pants tells
        nFPM to use this value as-is.
        """
    )
    # We can't use just the enum because we need to special case using this.
    # valid_choices = GoArch


class NfpmPlatformField(StringField):
    nfpm_alias = "platform"
    alias = nfpm_alias
    valid_choices = GoOS
    default = GoOS.linux.value  # based on nFPM default
    help = help_text(
        """
        The package platform.

        This should be a valid GOOS value that nFPM can translate
        into the package-specific equivalent.
        """
    )


class NfpmHomepageField(StringField):
    nfpm_alias = "homepage"
    alias = nfpm_alias
    help = help_text(
        lambda: f"""
        The URL of this package's homepage like "https://example.com".

        This field is named "{NfpmHomepageField.alias}" instead of "url" because
        that is the term used by nFPM, which adopted the term from deb packaging.
        The term "url" is used by apk, archlinux, and rpm packaging.
        """
    )


class NfpmLicenseField(StringField):
    nfpm_alias = "license"
    alias = nfpm_alias
    help = help_text(
        """
        The license of this package.

        Where possible, please try to use the SPDX license identifiers (for
        example "Apache-2.0", "BSD-3-Clause", "GPL-3.0-or-later", or "MIT"):
        https://spdx.org/licenses/

        For more complex cases, where the package includes software with multiple
        licenses, consider using an SPDX license expression:
        https://spdx.github.io/spdx-spec/v2.3/SPDX-license-expressions/

        See also these rpm-specific descriptions of how to set this field (this
        is helpful info even if you are not using rpm):
        https://docs.fedoraproject.org/en-US/legal/license-field/

        nFPM does not yet generate the debian/copyright file, so this field is
        technically unused for now. Even for deb, we recommend using this field
        to document the software license for this package. See also these pages
        about specifying a license for deb packaging:
        https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/#license-specification
        https://wiki.debian.org/Proposals/CopyrightFormat#Differences_between_DEP5_and_SPDX
        """
    )


APK_FIELDS = (
    NfpmPackageNameField,
    NfpmArchField,
    # version fields (apk does NOT get: version_metadata or epoch)
    NfpmVersionField,
    NfpmVersionSchemaField,
    NfpmVersionPrereleaseField,
    NfpmVersionReleaseField,
    # other package metadata fields
    NfpmHomepageField,
    NfpmLicenseField,
    NfpmApkMaintainerField,
)


class NfpmApkPackage(Target):
    alias = "nfpm_apk_package"
    core_fields = (
        *COMMON_TARGET_FIELDS,  # tags, description
        OutputPathField,
        *APK_FIELDS,
    )
    help = help_text(
        f""""
        An APK system package built by nFPM.

        This will not install the package, only create an .apk file
        that you can then distribute and install, e.g. via pkg.

        See {doc_url('nfpm-apk-package')}.
        """
    )


ARCHLINUX_FIELDS = (
    NfpmPackageNameField,
    NfpmArchField,
    # version fields (archlinux does NOT get: version_metadata)
    NfpmVersionField,
    NfpmVersionSchemaField,
    NfpmVersionPrereleaseField,
    NfpmVersionReleaseField,
    NfpmVersionEpochField,
    # other package metadata fields
    NfpmHomepageField,
    NfpmLicenseField,
    NfpmArchlinuxPackagerField,
    NfpmArchlinuxPkgbaseField,
)


class NfpmArchlinuxPackage(Target):
    alias = "nfpm_archlinux_package"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OutputPathField,
        *ARCHLINUX_FIELDS,
    )
    help = help_text(
        f""""
        An Archlinux system package built by nFPM.

        This will not install the package, only create an .tar.zst file
        that you can then distribute and install, e.g. via pkg.

        See {doc_url('nfpm-archlinux-package')}.
        """
    )


DEB_FIELDS = (
    NfpmPackageNameField,
    NfpmArchField,
    NfpmPlatformField,
    # version fields
    NfpmVersionField,
    NfpmVersionSchemaField,
    NfpmVersionPrereleaseField,
    NfpmVersionMetadataField,
    NfpmVersionReleaseField,
    NfpmVersionEpochField,
    # other package metadata fields
    NfpmHomepageField,
    NfpmLicenseField,  # not used by nFPM yet.
    NfpmDebMaintainerField,
    NfpmDebSectionField,
    NfpmDebPriorityField,
)


class NfpmDebPackage(Target):
    alias = "nfpm_deb_package"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OutputPathField,
        *DEB_FIELDS,
    )
    help = help_text(
        f""""
        A Debian system package built by nFPM.

        This will not install the package, only create a .deb file
        that you can then distribute and install, e.g. via pkg.

        See {doc_url('nfpm-deb-package')}.
        """
    )


RPM_FIELDS = (
    NfpmPackageNameField,
    NfpmArchField,
    NfpmPlatformField,
    # version fields
    NfpmVersionField,
    NfpmVersionSchemaField,
    NfpmVersionPrereleaseField,
    NfpmVersionMetadataField,
    NfpmVersionReleaseField,
    NfpmVersionEpochField,
    # other package metadata fields
    NfpmHomepageField,
    NfpmLicenseField,
    NfpmRpmPackagerField,
    NfpmRpmVendorField,
    NfpmRpmGroupField,
    NfpmRpmSummaryField,
)


class NfpmRpmPackage(Target):
    alias = "nfpm_rpm_package"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OutputPathField,
        *RPM_FIELDS,
    )
    help = help_text(
        f""""
        An RPM system package built by nFPM.

        This will not install the package, only create an .rpm file
        that you can then distribute and install, e.g. via pkg.

        See {doc_url('nfpm-rpm-package')}.
        """
    )
