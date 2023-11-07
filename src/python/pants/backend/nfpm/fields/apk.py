# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import ClassVar

from pants.backend.nfpm.fields._relationships import NfpmPackageRelationshipsField
from pants.engine.target import StringField
from pants.util.strutil import help_text

# These fields are used by the `nfpm_apk_package` target
# Some fields will be duplicated by other package types which
# allows the help string to be packager-specific.


class NfpmApkMaintainerField(StringField):
    nfpm_alias = "maintainer"
    alias: ClassVar[str] = nfpm_alias
    help = help_text(
        # based in part on the docs at:
        # https://nfpm.goreleaser.com/configuration/#reference
        lambda: f"""
        The name and email address of the packager or packager organization.

        The '{NfpmApkMaintainerField.alias}' is used to identify who actually
        packaged the software, as opposed to the author of the software.

        The name is first, then the email address inside angle brackets `<>`
        (in RFC5322 format). For example: "Foo Bar <maintainer@example.com>"

        See: https://wiki.alpinelinux.org/wiki/Apk_spec#PKGINFO_Format
        """
    )
    # During signing nFPM parses with mail.ParseAddress() which uses RFC5322
    # (RFC 5322 supersedes RFC 2822 which supersedes RFC 822).
    # Otherwise, nFPM embeds this string as-is in the apk package.


class NfpmApkReplacesField(NfpmPackageRelationshipsField):
    nfpm_alias = "replaces"
    alias: ClassVar[str] = nfpm_alias
    help = help_text(
        lambda: f"""
        A list of packages whose files this package can take ownership of.

        WARNING: This field does NOT have the same semantics as "replaces" in
        other packaging systems. This field deals with allowing packages that
        want to provide the same file to be installed at the same time.

        If another package '{NfpmApkProvidesField.alias}' the same file, and that
        package is in the '{NfpmApkReplacesField.alias}' list, then the apk
        installer will allow both packages to be installed and record that this
        package owns the conflicting files.

        This field takes a simple list of package names, like this:

        - "bash"
        - "git"
        - "pkgconfig"

        See:
        https://wiki.alpinelinux.org/wiki/Apk_spec#PKGINFO_Format
        https://wiki.alpinelinux.org/wiki/APKBUILD_Reference#replaces
        """
    )


class NfpmApkProvidesField(NfpmPackageRelationshipsField):
    nfpm_alias = "provides"
    alias: ClassVar[str] = nfpm_alias
    help = help_text(
        lambda: f"""
        A list of (virtual) packages or other things that this package provides.

        The '{NfpmApkProvidesField.alias}' field takes a variety of different formats.
        You can provide package alternatives, virtual packages, or various packaged
        components (commands, shared objects, pkg-config, etc). A "provides" entry
        with a version specifier defines an alternative name for this package that
        will conflict with any other package that has or provides that name.
        A "provides" entry without a version specifier defines a virtual package
        that does not create conflicts; multiple packages with the same virtual
        package (no version specifier) can be installed at the same time.

        Sadly, the format of this field is not very well documented, so you may
        have to open other packages to find examples of how to use it. The format
        seems to be very similar to the '{NfpmApkDependsField.alias}' field.

        Here are some examples extracted a variety of random packages:

        - "cmd:bash=5.2.15-r0"
        - "cmd:git=2.38.5-r0"
        - "cmd:gio=2.74.6-r0"
        - "so:libgio-2.0.so.0=0.7400.6"
        - "so:libglib-2.0.so.0=0.7400.6"
        - "py3.10:pkgconfig=1.5.5-r1"
        - "pc:libpkgconf=1.9.4"
        - "pkgconfig=1"

        See:
        https://wiki.alpinelinux.org/wiki/Apk_spec#PKGINFO_Format
        https://wiki.alpinelinux.org/wiki/APKBUILD_Reference#provides
        """
    )


class NfpmApkDependsField(NfpmPackageRelationshipsField):
    nfpm_alias = "depends"
    alias: ClassVar[str] = nfpm_alias  # TODO: this might be confused with "dependencies"
    help = help_text(
        lambda: f"""
        List of package dependencies or conflicts (for package installers).

        To specify a conflicting dependency (a package that cannot be installed
        at the same time), prefix the entry with a `!`.

        This field is named "{NfpmApkDependsField.alias}" because that is the
        term used by nFPM. Alpine linux uses both "depends" and "depend", which
        are used in APKBUILD and PKGINFO files respectively. The `abuild` tool
        uses the APKBUILD "depends" var--and other build-time introspection--to
        generate the PKGINFO "depend" var that ends up in the final apk package.

        The Alpine documentation says not to include shared-object dependencies
        in the APKBUILD "depends" var, but that warning does not apply to this
        field. Even though this field is named "{NfpmApkDependsField.alias}",
        nFPM uses it to build the PKGINFO "depend" var, so you SHOULD include any
        shared-object dependencies in this list.

        The '{NfpmApkDependsField.alias}' field takes a variety of different formats.
        You can depend on packages, absolute paths, shared objects, pkg-configs,
        and possibly other things. Sadly, that format is not very well documented,
        so you may have to open other packages to find examples of how to use
        pkg-config deps (which have a `pc:` prefix), and any other less common
        syntax. Here are some examples extracted a variety of random packages:

        Example package dependencies (which do not have a prefix):

        - "git"
        - "git=2.40.1-r0"

        Example absolute path dependencies (which start with `/`):

        - "/bin/sh"

        Example shared object dependencies (which have a `so:` prefix):

        - "so:libc.musl-x86_64.so.1"
        - "so:libcurl.so.4"
        - "so:libpcre2-8.so.0"
        - "so:libz.so.1"

        WARNING: This is NOT the same as the 'dependencies' field!
        It does not accept pants-style dependencies like target addresses.

        See: https://wiki.alpinelinux.org/wiki/Apk_spec#PKGINFO_Format

        See also the related (but different!) "depends" var in APKBUILD:
        https://wiki.alpinelinux.org/wiki/APKBUILD_Reference#depends
        https://wiki.alpinelinux.org/wiki/Creating_an_Alpine_package#depends_&_makedepends
        """
        # apkbuild uses the 'scanelf' binary, and the 'scan_shared_objects',
        # 'find_scanelf_paths', and 'trace_apk_deps' functions in abuild.in
        # to autodetect deps when generating the PKGINFO file.
        # https://git.alpinelinux.org/abuild/tree/abuild.in
        # nFPM does not do that.
        # TODO: maybe analyze the pants-built artifacts to generate this like abuild does
    )
