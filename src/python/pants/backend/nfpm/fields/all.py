# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from enum import Enum
from typing import ClassVar

from pants.core.goals.package import OutputPathField
from pants.engine.target import Dependencies, StringField
from pants.util.docutil import bin_name
from pants.util.strutil import help_text


class NfpmPackageNameField(StringField):
    nfpm_alias = "name"
    alias: ClassVar[str] = "package_name"
    required = True
    value: str
    help = help_text(
        """
        The package name.
        """
    )


class NfpmDependencies(Dependencies):
    nfpm_alias = ""  # doesn't map directly to a nfpm.yaml field


class NfpmArch(Enum):
    # nFPM uses arch = GOARCH + GOARM. See: https://nfpm.goreleaser.com/goarch-to-pkg/
    # GOARCH possible values come from `okgoarch` var at:
    # https://github.com/golang/go/blob/go1.20.3/src/cmd/dist/build.go#L62-L79
    # GOARM possible values come from `goarm()` func at:
    # https://github.com/golang/go/blob/go1.20.3/src/internal/buildcfg/cfg.go#L77-L84
    _386 = "386"
    all = "all"  # not in `okgoarch`, but a conventionally accepted GOARCH value.
    amd64 = "amd64"
    arm5 = "arm5"  # GOARCH=arm GOARM=5
    arm6 = "arm6"  # GOARCH=arm GOARM=6
    arm7 = "arm7"  # GOARCH=arm GOARM=7
    arm64 = "arm64"  # GOARCH=arm64
    loong64 = "loong64"
    mips = "mips"
    mipsle = "mipsle"
    mips64 = "mips64"
    mips64le = "mips64le"
    ppc64 = "ppc64"
    ppc64le = "ppc64le"
    riscv64 = "riscv64"
    s390 = "s390"  # not in `okgoarch`; nFPM translates it to "s390x".
    s390x = "s390x"
    sparc64 = "sparc64"
    wasm = "wasm"


class NfpmArchField(StringField):
    nfpm_alias = "arch"
    alias: ClassVar[str] = nfpm_alias
    # valid_choices = NfpmArch  # no valid_choices to support pass-through values.
    default = NfpmArch.amd64.value  # based on nFPM default
    help = help_text(
        f"""
        The package architecture.

        This should be a valid GOARCH value (or GOARCH+GOARM) that nFPM can
        convert into the package-specific equivalent. Otherwise, pants tells
        nFPM to use this value as-is.

        nFPM conversion from GOARCH to package-specific value is documented here:
        https://nfpm.goreleaser.com/goarch-to-pkg/

        Use one of these values unless you need nFPM to use your value as-is:
        {", ".join(repr(arch.value) for arch in NfpmArch.__members__.values())}
        """
    )


class NfpmPlatformField(StringField):
    nfpm_alias = "platform"
    alias: ClassVar[str] = nfpm_alias
    # no valid_choices to support pass-through values.
    default = "linux"  # based on nFPM default
    help = help_text(
        """
        The package platform or OS.

        You probably do not need to change the package's OS. nFPM is designed
        with the assumption that this is a GOOS value (since nFPM is part of the
        "goreleaser" project). But, nFPM does not do much with it.

        For archlinux and apk, the only valid value is 'linux'.
        For deb, this can be used as part of the 'Architecture' entry.
        For rpm, this populates the "OS" tag.
        """
    )


class NfpmHomepageField(StringField):
    nfpm_alias = "homepage"
    alias: ClassVar[str] = nfpm_alias
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
    alias: ClassVar[str] = nfpm_alias
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


class NfpmOutputPathField(OutputPathField):
    nfpm_alias = ""
    help = help_text(
        f"""
        Where the built directory tree should be located.

        If undefined, this will use the path to the BUILD file, followed by the target name.
        For example, `src/project/packaging:rpm` would be `src.project.packaging/rpm/`.

        Regardless of whether you use the default or set this field, the package's file name
        will have the packaging system's conventional filename (as understood by nFPM).
        So, an rpm using the default for this field, the target `src/project/packaging:rpm`
        might have a final path like `src.project.packaging/rpm/projectname-1.2.3-1.x86_64.rpm`.
        Similarly, for deb, the target `src/project/packaging:deb` might have a final path like
        `src.project.packaging/deb/projectname_1.2.3+git-1_x86_64.deb`. The other packagers
        have their own formats as well.

        When running `{bin_name()} package`, this path will be prefixed by `--distdir` (e.g. `dist/`).

        Warning: setting this value risks naming collisions with other package targets you may have.
        """
    )
