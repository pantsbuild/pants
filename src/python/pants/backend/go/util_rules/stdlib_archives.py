# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Pre-compiled Go standard library archives.

Instead of compiling each standard library package as its own build action (one or more
processes per package, ~90+ packages in a typical closure), ask the Go toolchain to compile
the entire standard library in a single `go install std` invocation and capture the resulting
`.a` archives. The archives are deterministic for a given toolchain configuration and are
keyed on `(go version, GOOS, GOARCH, cgo_enabled)`, so the harvest runs once per
configuration and is cached forever.

This mirrors the architecture used by Bazel's rules_go, which compiles the standard library
once per configuration in the same way; see
https://github.com/bazel-contrib/rules_go/blob/master/go/tools/builders/stdlib.go.

The archives are only usable for build configurations that match how `go install std`
compiles the standard library; `stdlib_archives_compatible` is the single gate deciding
whether a given `GoBuildOptions` can use them. Incompatible configurations (race/msan/asan,
code coverage, custom compiler or assembler flags) fall back to compiling the standard
library from source, exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.backend.go.util_rules import sdk
from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.backend.go.util_rules.goroot import GoRoot
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.engine.fs import EMPTY_DIGEST, Digest, FileEntry
from pants.engine.intrinsics import get_digest_entries
from pants.engine.process import execute_process_or_raise
from pants.engine.rules import collect_rules, implicitly, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

# Directory within the harvest sandbox (and within consuming sandboxes) under which the
# standard library archives are laid out, mirroring import paths: `__go_stdlib__/<import_path>.a`.
PKGDIR_PREFIX = "__go_stdlib__"


@dataclass(frozen=True)
class GoStdlibArchivesRequest:
    """Request the pre-compiled standard library archives for the current Go toolchain.

    `cgo_enabled` is a cache-key dimension, not a compatibility gate: the contents of some
    archives (e.g. `net`, `os/user`) differ between the cgo and non-cgo configurations, and
    `runtime/cgo` only exists in the cgo configuration, so each configuration is harvested
    separately. Other content-affecting options (race/msan/asan, coverage, custom compiler or
    assembler flags) are deliberately *not* dimensions here: rather than harvest a variant for
    each, `stdlib_archives_compatible` disqualifies them entirely and the build falls back to
    compiling the standard library from source package-by-package, as before.
    """

    cgo_enabled: bool


@dataclass(frozen=True)
class GoStdlibArchives:
    """Pre-compiled standard library archives, laid out as `__go_stdlib__/<import_path>.a`.

    `import_paths_to_pkg_a_files` maps each import path to its archive path within `digest`,
    e.g. `"fmt" -> "__go_stdlib__/fmt.a"`. A small number of standard library packages have no
    archive (e.g. `unsafe`, which has no compiled form): consumers must treat a missing key as
    "fall back to compiling that package from source".

    The mapping is empty when the toolchain cannot produce archives (Go < 1.20); consumers
    must then fall back to from-source compilation for all standard library packages.
    """

    digest: Digest
    import_paths_to_pkg_a_files: FrozenDict[str, str]


def stdlib_archives_compatible(build_opts: GoBuildOptions, golang: GolangSubsystem) -> bool:
    """Whether `build_opts` can link against pre-compiled standard library archives.

    The archives are compiled by `go install std` with the toolchain's default settings, so
    any option that changes the *content* of a standard library archive disqualifies them:
    race/msan/asan instrumentation, code coverage, and custom compiler or assembler flags.

    `cgo_enabled` is deliberately not checked: it is part of the harvest cache key (the cgo
    and non-cgo archive sets are harvested separately). `linker_flags` is deliberately not
    checked: linker flags apply at the final link step only and never affect the content of a
    package archive.
    """
    return (
        golang.use_prebuilt_stdlib_archives
        and build_opts.coverage_config is None
        and not build_opts.with_race_detector
        and not build_opts.with_msan
        and not build_opts.with_asan
        and not build_opts.compiler_flags
        and not build_opts.assembler_flags
    )


@rule(desc="Compile Go standard library archives", level=LogLevel.DEBUG)
async def harvest_go_stdlib_archives(
    request: GoStdlibArchivesRequest, goroot: GoRoot
) -> GoStdlibArchives:
    if not goroot.is_compatible_version("1.20"):
        # `GODEBUG=installgoroot=all` (which makes `go install std` write archives for every
        # standard library package even with `-pkgdir`) was introduced in Go 1.20. Return an
        # empty mapping; consumers fall back to compiling the standard library from source.
        return GoStdlibArchives(EMPTY_DIGEST, FrozenDict({}))

    # Note: `-trimpath` keeps the archives free of absolute build paths and `-pkgdir` accepts a
    # path relative to the sandbox root, so the output is fully deterministic for a given
    # toolchain configuration (verified byte-identical across separate cold builds in different
    # directories). The toolchain configuration itself is captured by the
    # `__PANTS_GO_SDK_CACHE_KEY` (version/GOOS/GOARCH) env var injected by `GoSdkProcess`, plus
    # `CGO_ENABLED` below, so a toolchain change re-runs the harvest atomically with all
    # package compiles.
    result = await execute_process_or_raise(
        **implicitly(
            GoSdkProcess(
                command=("install", "-trimpath", "-pkgdir", PKGDIR_PREFIX, "std"),
                env={
                    # The critical setting: `installgoroot=all` makes `go install -pkgdir` write
                    # an archive for *every* standard library package into `-pkgdir`, rather than
                    # only the handful not already present in GOROOT. Without it the harvest is
                    # nearly empty. Introduced in Go 1.20 (gated on the version check above).
                    "GODEBUG": "installgoroot=all",
                    "CGO_ENABLED": "1" if request.cgo_enabled else "0",
                },
                description="Compile Go standard library archives",
                output_directories=(PKGDIR_PREFIX,),
            )
        )
    )

    entries = await get_digest_entries(result.output_digest)
    mapping = {
        # e.g. "__go_stdlib__/crypto/sha256.a" -> import path "crypto/sha256"
        entry.path[len(PKGDIR_PREFIX) + 1 : -len(".a")]: entry.path
        for entry in entries
        if isinstance(entry, FileEntry) and entry.path.endswith(".a")
    }
    if not mapping:
        raise ValueError(
            "Pants ran `go install -pkgdir ... std` to pre-compile the Go standard library, "
            "but no archives were produced. This may indicate that the "
            "`GODEBUG=installgoroot=all` setting is no longer honored by your Go version "
            f"({goroot.full_version}). Set `[golang].use_prebuilt_stdlib_archives = false` "
            "in `pants.toml` to fall back to per-package compilation of the standard "
            "library, and report this issue at https://github.com/pantsbuild/pants/issues/new."
        )

    return GoStdlibArchives(result.output_digest, FrozenDict(mapping))


def rules():
    return (
        *collect_rules(),
        *sdk.rules(),
    )
