# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import re
import string
from typing import Iterable, Sequence

from pants.util.memo import memoized

#
# Check compiler and linker arguments in CGo use cases against explicit allow lists.
# Adapted from https://github.com/golang/go/blob/master/src/cmd/go/internal/work/security.go.
#
# Original copyright:
#   // Copyright 2018 The Go Authors. All rights reserved.
#   // Use of this source code is governed by a BSD-style
#   // license that can be found in the LICENSE file.


class CGoFlagSecurityError(ValueError):
    pass


@memoized
def _valid_compiler_flags() -> tuple[re.Pattern, ...]:
    return (
        re.compile(r"-D([A-Za-z_][A-Za-z0-9_]*)(=[^@\-]*)?"),
        re.compile(r"-U([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"-F([^@\-].*)"),
        re.compile(r"-I([^@\-].*)"),
        re.compile(r"-O"),
        re.compile(r"-O([^@\-].*)"),
        re.compile(r"-W"),
        re.compile(r"-W([^@,]+)"),  # -Wall but not -Wa,-foo.
        re.compile(r"-Wa,-mbig-obj"),
        re.compile(r"-Wp,-D([A-Za-z_][A-Za-z0-9_]*)(=[^@,\-]*)?"),
        re.compile(r"-Wp,-U([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"-ansi"),
        re.compile(r"-f(no-)?asynchronous-unwind-tables"),
        re.compile(r"-f(no-)?blocks"),
        re.compile(r"-f(no-)builtin-[a-zA-Z0-9_]*"),
        re.compile(r"-f(no-)?common"),
        re.compile(r"-f(no-)?constant-cfstrings"),
        re.compile(r"-fdiagnostics-show-note-include-stack"),
        re.compile(r"-f(no-)?eliminate-unused-debug-types"),
        re.compile(r"-f(no-)?exceptions"),
        re.compile(r"-f(no-)?fast-math"),
        re.compile(r"-f(no-)?inline-functions"),
        re.compile(r"-finput-charset=([^@\-].*)"),
        re.compile(r"-f(no-)?fat-lto-objects"),
        re.compile(r"-f(no-)?keep-inline-dllexport"),
        re.compile(r"-f(no-)?lto"),
        re.compile(r"-fmacro-backtrace-limit=(.+)"),
        re.compile(r"-fmessage-length=(.+)"),
        re.compile(r"-f(no-)?modules"),
        re.compile(r"-f(no-)?objc-arc"),
        re.compile(r"-f(no-)?objc-nonfragile-abi"),
        re.compile(r"-f(no-)?objc-legacy-dispatch"),
        re.compile(r"-f(no-)?omit-frame-pointer"),
        re.compile(r"-f(no-)?openmp(-simd)?"),
        re.compile(r"-f(no-)?permissive"),
        re.compile(r"-f(no-)?(pic|PIC|pie|PIE)"),
        re.compile(r"-f(no-)?plt"),
        re.compile(r"-f(no-)?rtti"),
        re.compile(r"-f(no-)?split-stack"),
        re.compile(r"-f(no-)?stack-(.+)"),
        re.compile(r"-f(no-)?strict-aliasing"),
        re.compile(r"-f(un)signed-char"),
        re.compile(r"-f(no-)?use-linker-plugin"),  # safe if -B is not used; we don't permit -B
        re.compile(r"-f(no-)?visibility-inlines-hidden"),
        re.compile(r"-fsanitize=(.+)"),
        re.compile(r"-ftemplate-depth-(.+)"),
        re.compile(r"-fvisibility=(.+)"),
        re.compile(r"-g([^@\-].*)?"),
        re.compile(r"-m32"),
        re.compile(r"-m64"),
        re.compile(r"-m(abi|arch|cpu|fpu|tune)=([^@\-].*)"),
        re.compile(r"-m(no-)?v?aes"),
        re.compile(r"-marm"),
        re.compile(r"-m(no-)?avx[0-9a-z]*"),
        re.compile(r"-mfloat-abi=([^@\-].*)"),
        re.compile(r"-mfpmath=[0-9a-z,+]*"),
        re.compile(r"-m(no-)?avx[0-9a-z.]*"),
        re.compile(r"-m(no-)?ms-bitfields"),
        re.compile(r"-m(no-)?stack-(.+)"),
        re.compile(r"-mmacosx-(.+)"),
        re.compile(r"-mios-simulator-version-min=(.+)"),
        re.compile(r"-miphoneos-version-min=(.+)"),
        re.compile(r"-mtvos-simulator-version-min=(.+)"),
        re.compile(r"-mtvos-version-min=(.+)"),
        re.compile(r"-mwatchos-simulator-version-min=(.+)"),
        re.compile(r"-mwatchos-version-min=(.+)"),
        re.compile(r"-mnop-fun-dllimport"),
        re.compile(r"-m(no-)?sse[0-9.]*"),
        re.compile(r"-m(no-)?ssse3"),
        re.compile(r"-mthumb(-interwork)?"),
        re.compile(r"-mthreads"),
        re.compile(r"-mwindows"),
        re.compile(r"--param=ssp-buffer-size=[0-9]*"),
        re.compile(r"-pedantic(-errors)?"),
        re.compile(r"-pipe"),
        re.compile(r"-pthread"),
        re.compile(r"-?-std=([^@\-].*)"),
        re.compile(r"-?-stdlib=([^@\-].*)"),
        re.compile(r"--sysroot=([^@\-].*)"),
        re.compile(r"-w"),
        re.compile(r"-x([^@\-].*)"),
        re.compile(r"-v"),
    )


_valid_compiler_flags_with_next_arg = (
    "-arch",
    "-D",
    "-U",
    "-I",
    "-F",
    "-framework",
    "-include",
    "-isysroot",
    "-isystem",
    "--sysroot",
    "-target",
    "-x",
)


@memoized
def _valid_linker_flags() -> tuple[re.Pattern, ...]:
    return (
        re.compile(r"-F([^@\-].*)"),
        re.compile(r"-l([^@\-].*)"),
        re.compile(r"-L([^@\-].*)"),
        re.compile(r"-O"),
        re.compile(r"-O([^@\-].*)"),
        re.compile(r"-f(no-)?(pic|PIC|pie|PIE)"),
        re.compile(r"-f(no-)?openmp(-simd)?"),
        re.compile(r"-fsanitize=([^@\-].*)"),
        re.compile(r"-flat_namespace"),
        re.compile(r"-g([^@\-].*)?"),
        re.compile(r"-headerpad_max_install_names"),
        re.compile(r"-m(abi|arch|cpu|fpu|tune)=([^@\-].*)"),
        re.compile(r"-mfloat-abi=([^@\-].*)"),
        re.compile(r"-mmacosx-(.+)"),
        re.compile(r"-mios-simulator-version-min=(.+)"),
        re.compile(r"-miphoneos-version-min=(.+)"),
        re.compile(r"-mthreads"),
        re.compile(r"-mwindows"),
        re.compile(r"-(pic|PIC|pie|PIE)"),
        re.compile(r"-pthread"),
        re.compile(r"-rdynamic"),
        re.compile(r"-shared"),
        re.compile(r"-?-static([-a-z0-9+]*)"),
        re.compile(r"-?-stdlib=([^@\-].*)"),
        re.compile(r"-v"),
        # Note that any wildcards in -Wl need to exclude comma,
        # since -Wl splits its argument at commas and passes
        # them all to the linker uninterpreted. Allowing comma
        # in a wildcard would allow tunneling arbitrary additional
        # linker arguments through one of these.
        re.compile(r"-Wl,--(no-)?allow-multiple-definition"),
        re.compile(r"-Wl,--(no-)?allow-shlib-undefined"),
        re.compile(r"-Wl,--(no-)?as-needed"),
        re.compile(r"-Wl,-Bdynamic"),
        re.compile(r"-Wl,-berok"),
        re.compile(r"-Wl,-Bstatic"),
        re.compile(r"-Wl,-Bsymbolic-functions"),
        re.compile(r"-Wl,-O([^@,\-][^,]*)?"),
        re.compile(r"-Wl,-d[ny]"),
        re.compile(r"-Wl,--disable-new-dtags"),
        re.compile(r"-Wl,-e[=,][a-zA-Z0-9]*"),
        re.compile(r"-Wl,--enable-new-dtags"),
        re.compile(r"-Wl,--end-group"),
        re.compile(r"-Wl,--(no-)?export-dynamic"),
        re.compile(r"-Wl,-E"),
        re.compile(r"-Wl,-framework,[^,@\-][^,]+"),
        re.compile(r"-Wl,--hash-style=(sysv|gnu|both)"),
        re.compile(r"-Wl,-headerpad_max_install_names"),
        re.compile(r"-Wl,--no-undefined"),
        re.compile(r"-Wl,-R([^@\-][^,@]*$)"),
        re.compile(r"-Wl,--just-symbols[=,]([^,@\-][^,@]+)"),
        re.compile(r"-Wl,-rpath(-link)?[=,]([^,@\-][^,]+)"),
        re.compile(r"-Wl,-s"),
        re.compile(r"-Wl,-search_paths_first"),
        re.compile(r"-Wl,-sectcreate,([^,@\-][^,]+),([^,@\-][^,]+),([^,@\-][^,]+)"),
        re.compile(r"-Wl,--start-group"),
        re.compile(r"-Wl,-?-static"),
        re.compile(r"-Wl,-?-subsystem,(native|windows|console|posix|xbox)"),
        re.compile(r"-Wl,-syslibroot[=,]([^,@\-][^,]+)"),
        re.compile(r"-Wl,-undefined[=,]([^,@\-][^,]+)"),
        re.compile(r"-Wl,-?-unresolved-symbols=[^,]+"),
        re.compile(r"-Wl,--(no-)?warn-([^,]+)"),
        re.compile(r"-Wl,-?-wrap[=,][^,@\-][^,]*"),
        re.compile(r"-Wl,-z,(no)?execstack"),
        re.compile(r"-Wl,-z,relro"),
        re.compile(
            r"[a-zA-Z0-9_/].*\.(a|o|obj|dll|dylib|so|tbd)"
        ),  # direct linker inputs: x.o or libfoo.so (but not -foo.o or @foo.o)
        re.compile(r"\./.*\.(a|o|obj|dll|dylib|so|tbd)"),
    )


_valid_linker_flags_with_next_arg = (
    "-arch",
    "-F",
    "-l",
    "-L",
    "-framework",
    "-isysroot",
    "--sysroot",
    "-target",
    "-Wl,-framework",
    "-Wl,-rpath",
    "-Wl,-R",
    "-Wl,--just-symbols",
    "-Wl,-undefined",
)


# SafeArg reports whether arg is a "safe" command-line argument,
# meaning that when it appears in a command-line, it probably
# doesn't have some special meaning other than its own name.
# Obviously args beginning with - are not safe (they look like flags).
# Less obviously, args beginning with @ are not safe (they look like
# GNU binutils flagfile specifiers, sometimes called "response files").
# To be conservative, we reject almost any arg beginning with non-alphanumeric ASCII.
# We accept leading . _ and / as likely in file system paths.
# There is a copy of this function in cmd/compile/internal/gc/noder.go.
def safe_arg(name: str) -> bool:
    if name == "":
        return False
    c = name[0]
    return (
        c in string.digits
        or c in string.ascii_letters
        or c == "."
        or c == "_"
        or c == "/"
        or ord(c) >= 0x80
    )


def _check_flags(
    flags: Sequence[str],
    regexps: Iterable[re.Pattern],
    valid_next_options: Iterable[str],
    source: str,
):
    i = 0
    while i < len(flags):
        flag = flags[i]
        continue_outer_loop = False
        for regexp in regexps:
            m = regexp.fullmatch(flag)
            if m:
                i = i + 1
                continue_outer_loop = True
                break

        if continue_outer_loop:
            continue

        for valid_next_option in valid_next_options:
            if valid_next_option == flag:
                if i + 1 < len(flags) and safe_arg(flags[i + 1]):
                    i = i + 2
                    continue_outer_loop = True
                    break

                # Permit -Wl,-framework -Wl,name.
                if (
                    i + 1 < len(flags)
                    and flag.startswith("-Wl,")
                    and flags[i + 1].startswith("-Wl,")
                    and safe_arg(flags[i + 1][4:])
                    and "," not in flags[i + 1][4:]
                ):
                    i = i + 2
                    continue_outer_loop = True
                    break

                # Permit -I= /path, -I $SYSROOT.
                if i + 1 < len(flags) and flag == "-I":
                    if (
                        flags[i + 1].startswith("=") or flags[i + 1].startswith("$SYSROOT")
                    ) and safe_arg(flags[i + 1][1:]):
                        i = i + 2
                        continue_outer_loop = True
                        break

                if i + 1 < len(flags):
                    raise CGoFlagSecurityError(
                        f"invalid flag in {source}: {flag} {flags[i+1]} (see https://golang.org/s/invalidflag)"
                    )

                raise CGoFlagSecurityError(
                    f"invalid flag in {source}: {flag} without argument (see https://golang.org/s/invalidflag)"
                )

        if continue_outer_loop:
            continue

        raise CGoFlagSecurityError(f"invalid flag in {source}: {flag}")


def check_compiler_flags(flags: Sequence[str], source: str):
    _check_flags(flags, _valid_compiler_flags(), _valid_compiler_flags_with_next_arg, source)


def check_linker_flags(flags: Sequence[str], source: str):
    _check_flags(flags, _valid_linker_flags(), _valid_linker_flags_with_next_arg, source)
