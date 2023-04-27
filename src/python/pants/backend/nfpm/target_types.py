# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum

from pants.core.goals.package import OutputPathField
from pants.engine.target import COMMON_TARGET_FIELDS, StringField, Target
from pants.util.docutil import doc_url
from pants.util.strutil import help_text


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
    alias = "arch"
    required = True
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
    alias = "platform"
    required = True
    help = help_text(
        """
        The package architecture.

        This should be a valid GOOS value that nFPM can translate
        into the package-specific equivalent.
        """
    )
    valid_choices = GoOS


class NfpmVersionField(StringField):
    alias = "version"
    required = True
    help = help_text(
        """
        The package version (preferably following semver).

        Some package managers, like deb, require the version start
        with a digit. Hence, you should not prefix the version with 'v'.
        """
    )

NFPM_COMMON_FIELDS = (
    # TODO: maybe add a package name field as well
    NfpmArchField,
    NfpmPlatformField,
    NfpmVersionField,
    # Other Version fields are package-specific, not COMMON
)


class NfpmApkPackage(Target):
    alias = "nfpm_apk_package"
    core_fields = (
        *COMMON_TARGET_FIELDS,  # tags, description
        OutputPathField,
        *NFPM_COMMON_FIELDS,
    )
    help = help_text(
        f""""
        An APK system package built by nFPM.

        This will not install the package, only create an .apk file
        that you can then distribute and install, e.g. via pkg.

        See {doc_url('nfpm-apk-package')}.
        """
    )


class NfpmArchlinuxPackage(Target):
    alias = "nfpm_archlinux_package"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OutputPathField,
        *NFPM_COMMON_FIELDS,
    )
    help = help_text(
        f""""
        An Archlinux system package built by nFPM.

        This will not install the package, only create an .tar.zst file
        that you can then distribute and install, e.g. via pkg.

        See {doc_url('nfpm-archlinux-package')}.
        """
    )


class NfpmDebPackage(Target):
    alias = "nfpm_deb_package"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OutputPathField,
        *NFPM_COMMON_FIELDS,
    )
    help = help_text(
        f""""
        A Debian system package built by nFPM.

        This will not install the package, only create a .deb file
        that you can then distribute and install, e.g. via pkg.

        See {doc_url('nfpm-deb-package')}.
        """
    )


class NfpmRpmPackage(Target):
    alias = "nfpm_rpm_package"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OutputPathField,
        *NFPM_COMMON_FIELDS,
    )
    help = help_text(
        f""""
        An RPM system package built by nFPM.

        This will not install the package, only create an .rpm file
        that you can then distribute and install, e.g. via pkg.

        See {doc_url('nfpm-rpm-package')}.
        """
    )
