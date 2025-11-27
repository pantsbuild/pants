# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

_libldap_soname = "libldap-2.5.so.0"
_libldap_so_file = "/usr/lib/{}-linux-gnu/" + _libldap_soname
_libldap_pkg = "libldap-2.5-0"

_libc6_soname = "libc.so.6"


def _libc6_pkgs(_arch: str, prof: bool = True) -> dict[str, list[str]]:
    pkgs = {}
    if prof:
        pkgs[f"/lib/libc6-prof/{_arch}-linux-gnu/{_libc6_soname}"] = ["libc6-prof"]
    pkgs[f"/lib/{_arch}-linux-gnu/{_libc6_soname}"] = ["libc6"]
    return dict(sorted(pkgs.items()))


_libc6_pkgs_amd64 = {  # only x86_64 not aarch64
    "/lib32/" + _libc6_soname: ["libc6-i386"],
    "/libx32/" + _libc6_soname: ["libc6-x32"],
}
_libc6_cross_pkgs = {
    f"/usr/{cross_machine}-linux-{cross_os_lib}/lib{cross_bits}/{_libc6_soname}": [
        f"libc6-{cross_arch}-cross"
    ]
    for cross_machine, cross_os_lib, cross_bits, cross_arch in [
        ("aarch64", "gnu", "", "arm64"),
        ("arm", "gnueabi", "", "armel"),
        ("arm", "gnueabihf", "", "armhf"),
        ("hppa", "gnu", "", "hppa"),
        ("i686", "gnu", "", "i386"),
        ("i686", "gnu", "64", "amd64-i386"),
        ("i686", "gnu", "x32", "x32-i386"),
        ("m68k", "gnu", "", "m68k"),
        ("mips", "gnu", "", "mips"),
        ("mips", "gnu", "32", "mipsn32-mips"),
        ("mips", "gnu", "64", "mips64-mips"),
        ("mips64", "gnuabi64", "", "mips64"),
        ("mips64", "gnuabi64", "32", "mipsn32-mips64"),
        ("mips64", "gnuabi64", "o32", "mips32-mips64"),
        ("mips64", "gnuabin32", "", "mipsn32"),
        ("mips64", "gnuabin32", "64", "mips64-mipsn32"),
        ("mips64", "gnuabin32", "o32", "mips32-mipsn32"),
        ("mips64el", "gnuabi64", "", "mips64el"),
        ("mips64el", "gnuabi64", "32", "mipsn32-mips64el"),
        ("mips64el", "gnuabi64", "o32", "mips32-mips64el"),
        ("mips64el", "gnuabin32", "", "mipsn32el"),
        ("mips64el", "gnuabin32", "64", "mips64-mipsn32el"),
        ("mips64el", "gnuabin32", "o32", "mips32-mipsn32el"),
        ("mipsel", "gnu", "", "mipsel"),
        ("mipsel", "gnu", "32", "mipsn32-mipsel"),
        ("mipsel", "gnu", "64", "mips64-mipsel"),
        ("mipsisa32r6", "gnu", "", "mipsr6"),
        ("mipsisa32r6", "gnu", "32", "mipsn32-mipsr6"),
        ("mipsisa32r6", "gnu", "64", "mips64-mipsr6"),
        ("mipsisa32r6el", "gnu", "", "mipsr6el"),
        ("mipsisa32r6el", "gnu", "32", "mipsn32-mipsr6el"),
        ("mipsisa32r6el", "gnu", "64", "mips64-mipsr6el"),
        ("mipsisa64r6", "gnuabi64", "", "mips64r6"),
        ("mipsisa64r6", "gnuabi64", "32", "mipsn32-mips64r6"),
        ("mipsisa64r6", "gnuabi64", "o32", "mips32-mips64r6"),
        ("mipsisa64r6", "gnuabin32", "", "mipsn32r6"),
        ("mipsisa64r6", "gnuabin32", "64", "mips64-mipsn32r6"),
        ("mipsisa64r6", "gnuabin32", "o32", "mips32-mipsn32r6"),
        ("mipsisa64r6el", "gnuabi64", "", "mips64r6el"),
        ("mipsisa64r6el", "gnuabi64", "32", "mipsn32-mips64r6el"),
        ("mipsisa64r6el", "gnuabi64", "o32", "mips32-mips64r6el"),
        ("mipsisa64r6el", "gnuabin32", "", "mipsn32r6el"),
        ("mipsisa64r6el", "gnuabin32", "64", "mips64-mipsn32r6el"),
        ("mipsisa64r6el", "gnuabin32", "o32", "mips32-mipsn32r6el"),
        ("powerpc", "gnu", "", "powerpc"),
        ("powerpc", "gnu", "64", "ppc64-powerpc"),
        ("powerpc64", "gnu", "", "ppc64"),
        ("powerpc64", "gnu", "32", "powerpc-ppc64"),
        ("powerpc64le", "gnu", "", "ppc64el"),
        ("riscv64", "gnu", "", "riscv64"),
        ("s390x", "gnu", "", "s390x"),
        ("s390x", "gnu", "32", "s390-s390x"),
        ("sh4", "gnu", "", "sh4"),
        ("sparc64", "gnu", "", "sparc64"),
        ("sparc64", "gnu", "32", "sparc-sparc64"),
        ("x86_64", "gnu", "", "amd64"),
        ("x86_64", "gnu", "32", "i386-amd64"),
        ("x86_64", "gnu", "x32", "x32-amd64"),
        ("x86_64", "gnux32", "", "x32"),
        ("x86_64", "gnux32", "32", "i386-x32"),
        ("x86_64", "gnux32", "64", "amd64-x32"),
    ]
}

TEST_CASES = (
    pytest.param(
        "debian",
        "bookworm",
        "amd64",
        (_libldap_soname,),
        {_libldap_soname: {_libldap_so_file.format("x86_64"): [_libldap_pkg]}},
        None,  # from_best_so_files is the same result
        id="debian-amd64-libldap",
    ),
    pytest.param(
        "debian",
        "bookworm",
        "arm64",
        (_libldap_soname,),
        {_libldap_soname: {_libldap_so_file.format("aarch64"): [_libldap_pkg]}},
        None,  # from_best_so_files is the same result
        id="debian-arm64-libldap",
    ),
    pytest.param(
        "ubuntu",
        "jammy",
        "amd64",
        (_libldap_soname,),
        {_libldap_soname: {_libldap_so_file.format("x86_64"): [_libldap_pkg]}},
        None,  # from_best_so_files is the same result
        id="ubuntu-amd64-libldap",
    ),
    pytest.param(
        "ubuntu",
        "jammy",
        "arm64",
        (_libldap_soname,),
        {_libldap_soname: {_libldap_so_file.format("aarch64"): [_libldap_pkg]}},
        None,  # from_best_so_files is the same result
        id="ubuntu-arm64-libldap",
    ),
    pytest.param(
        "ubuntu", "foobar", "amd64", (_libldap_soname,), {}, None, id="bad-distro_codename"
    ),
    pytest.param("ubuntu", "jammy", "foobar", (_libldap_soname,), {}, None, id="bad-debian_arch"),
    pytest.param("ubuntu", "jammy", "amd64", ("foobarbaz-9.9.so.9",), {}, None, id="bad-soname"),
    pytest.param(
        "ubuntu",
        "jammy",
        "amd64",
        ("libcurl.so",),  # the search api returns a table like this:
        # ------------------------------------------- | ----------------------------------------------------------- |
        # File                                        | Packages                                                    |
        # ------------------------------------------- | ----------------------------------------------------------- |
        # /usr/lib/cupt4-2/downloadmethods/libcurl.so | libcupt4-2-downloadmethod-curl                              |
        # /usr/lib/x86_64-linux-gnu/libcurl.so        | libcurl4-gnutls-dev, libcurl4-nss-dev, libcurl4-openssl-dev |
        # ------------------------------------------- | ----------------------------------------------------------- |
        {
            "libcurl.so": {
                "/usr/lib/cupt4-2/downloadmethods/libcurl.so": ["libcupt4-2-downloadmethod-curl"],
                "/usr/lib/x86_64-linux-gnu/libcurl.so": [
                    "libcurl4-gnutls-dev",
                    "libcurl4-nss-dev",
                    "libcurl4-openssl-dev",
                ],
            }
        },
        {  # from_best_so_files is NOT the same result
            "libcurl.so": {
                "/usr/lib/x86_64-linux-gnu/libcurl.so": [
                    "libcurl4-gnutls-dev",
                    "libcurl4-nss-dev",
                    "libcurl4-openssl-dev",
                ],
            }
        },
        id="same-file-in-multiple-packages",
    ),
    pytest.param(
        "ubuntu",
        "jammy",
        "amd64",
        (_libc6_soname,),
        {_libc6_soname: _libc6_pkgs("x86_64") | _libc6_pkgs_amd64 | _libc6_cross_pkgs},
        {_libc6_soname: _libc6_pkgs("x86_64", prof=False)},
        id="ubuntu-amd64-libc6",
    ),
    pytest.param(
        "ubuntu",
        "jammy",
        "arm64",
        (_libc6_soname,),
        {_libc6_soname: _libc6_pkgs("aarch64") | _libc6_cross_pkgs},
        {_libc6_soname: _libc6_pkgs("aarch64", prof=False)},
        id="ubuntu-arm64-libc6",
    ),
)
