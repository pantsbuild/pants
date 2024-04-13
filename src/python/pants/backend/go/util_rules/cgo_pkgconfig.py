# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.go.util_rules import cgo_binaries
from pants.backend.go.util_rules.cgo_binaries import CGoBinaryPathRequest
from pants.backend.go.util_rules.cgo_security import (
    check_compiler_flags,
    check_linker_flags,
    safe_arg,
)
from pants.core.util_rules.system_binaries import BinaryPath, BinaryPathTest
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, rule

# Adapted from the Go toolchain
#
# Original copyright:
#   // Copyright 2011 The Go Authors. All rights reserved.
#   // Use of this source code is governed by a BSD-style
#   // license that can be found in the LICENSE file.


@dataclass(frozen=True)
class CGoPkgConfigFlagsRequest:
    """Request resolution of pkg-config arguments into CFLAGS and LDFLAGS."""

    pkg_config_args: tuple[str, ...]


@dataclass(frozen=True)
class CGoPkgConfigFlagsResult:
    cflags: tuple[str, ...]
    ldflags: tuple[str, ...]


# _split_pkg_config_output parses the pkg-config output into a tuple of flags. This implements the algorithm from
# https://github.com/pkgconf/pkgconf/blob/master/libpkgconf/argvsplit.c
# See https://github.com/golang/go/blob/54182ff54a687272dd7632c3a963e036ce03cb7c/src/cmd/go/internal/work/exec.go#L1414-L1473
def _split_pkg_config_output(content: bytes) -> tuple[str, ...]:
    if not content:
        return ()

    flags: list[str] = []
    flag = bytearray()
    escaped = False
    quote = 0
    for c in content:
        if escaped:
            if quote != 0:
                if c not in b'$`"\\':
                    flag.extend(b"\\")
                flag.append(c)
            else:
                flag.append(c)
            escaped = False
        elif quote != 0:
            if c == quote:
                quote = 0
            else:
                if c == ord("\\"):
                    escaped = True
                else:
                    flag.append(c)
        elif c not in b" \t\n\v\f\r":
            if c == ord(b"\\"):
                escaped = True
            elif c in b"'\"":
                quote = c
            else:
                flag.append(c)
        elif len(flag) != 0:
            flags.append(flag.decode())
            flag = bytearray()

    if escaped:
        raise ValueError("broken character escaping in pkg-config output")
    if quote != 0:
        raise ValueError("unterminated quoted string in pkgconf output")
    elif len(flag) != 0:
        flags.append(flag.decode())

    return tuple(flags)


@rule
async def resolve_cgo_pkg_config_args(request: CGoPkgConfigFlagsRequest) -> CGoPkgConfigFlagsResult:
    if not request.pkg_config_args:
        return CGoPkgConfigFlagsResult(cflags=(), ldflags=())

    pkg_config_flags = []
    pkgs = []
    for arg in request.pkg_config_args:
        if arg == "--":
            # Skip the `--` separator as we will add our own later.
            pass
        elif arg.startswith("--"):
            pkg_config_flags.append(arg)
        else:
            pkgs.append(arg)

    for pkg in pkgs:
        if not safe_arg(pkg):
            raise ValueError(f"invalid pkg-config package name: {pkg}")

    pkg_config_path = await Get(
        BinaryPath,
        CGoBinaryPathRequest(
            binary_name="pkg-config",
            binary_path_test=BinaryPathTest(["--version"]),
        ),
    )

    cflags_result, ldflags_result = await MultiGet(
        Get(
            ProcessResult,
            Process(
                argv=[pkg_config_path.path, "--cflags", *pkg_config_flags, "--", *pkgs],
                description=f"Run pkg-config for CFLAGS for packages: {pkgs}",
            ),
        ),
        Get(
            ProcessResult,
            Process(
                argv=[pkg_config_path.path, "--libs", *pkg_config_flags, "--", *pkgs],
                description=f"Run pkg-config for LDFLAGS for packages: {pkgs}",
            ),
        ),
    )

    cflags: tuple[str, ...] = ()
    if cflags_result.stdout:
        cflags = _split_pkg_config_output(cflags_result.stdout)
        check_compiler_flags(cflags, "pkg-config --cflags")

    ldflags: tuple[str, ...] = ()
    if ldflags_result.stdout:
        # NOTE: we don't attempt to parse quotes and unescapes here. pkg-config
        # is typically used within shell backticks, which treats quotes literally.
        ldflags = tuple(arg.decode() for arg in ldflags_result.stdout.split())
        check_linker_flags(ldflags, "pkg-config --libs")

    return CGoPkgConfigFlagsResult(cflags=cflags, ldflags=ldflags)


def rules():
    return (
        *collect_rules(),
        *cgo_binaries.rules(),
    )
