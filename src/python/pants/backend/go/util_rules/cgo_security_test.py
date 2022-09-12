# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import pytest

from pants.backend.go.util_rules.cgo_security import (
    CGoFlagSecurityError,
    check_compiler_flags,
    check_linker_flags,
)

# Check compiler and linker arguments in CGo use cases against explicit allow lists.
# Adapted from https://github.com/golang/go/blob/master/src/cmd/go/internal/work/security_test.go.
#
# Original copyright:
#   // Copyright 2018 The Go Authors. All rights reserved.
#   // Use of this source code is governed by a BSD-style
#   // license that can be found in the LICENSE file.

GOOD_COMPILER_FLAGS = (
    ("-DFOO",),
    ("-Dfoo=bar",),
    ("-Ufoo",),
    ("-Ufoo1",),
    ("-F/Qt",),
    (
        "-F",
        "/Qt",
    ),
    ("-I/",),
    ("-I/etc/passwd",),
    ("-I.",),
    ("-O",),
    ("-O2",),
    ("-Osmall",),
    ("-W",),
    ("-Wall",),
    ("-Wp,-Dfoo=bar",),
    ("-Wp,-Ufoo",),
    ("-Wp,-Dfoo1",),
    ("-Wp,-Ufoo1",),
    ("-fobjc-arc",),
    ("-fno-objc-arc",),
    ("-fomit-frame-pointer",),
    ("-fno-omit-frame-pointer",),
    ("-fpic",),
    ("-fno-pic",),
    ("-fPIC",),
    ("-fno-PIC",),
    ("-fpie",),
    ("-fno-pie",),
    ("-fPIE",),
    ("-fno-PIE",),
    ("-fsplit-stack",),
    ("-fno-split-stack",),
    ("-fstack-xxx",),
    ("-fno-stack-xxx",),
    ("-fsanitize=hands",),
    ("-g",),
    ("-ggdb",),
    ("-march=souza",),
    ("-mcpu=123",),
    ("-mfpu=123",),
    ("-mtune=happybirthday",),
    ("-mstack-overflow",),
    ("-mno-stack-overflow",),
    ("-mmacosx-version",),
    ("-mnop-fun-dllimport",),
    ("-pthread",),
    ("-std=c99",),
    ("-xc",),
    (
        "-D",
        "FOO",
    ),
    (
        "-D",
        "foo=bar",
    ),
    (
        "-I",
        ".",
    ),
    (
        "-I",
        "/etc/passwd",
    ),
    (
        "-I",
        "世界",
    ),
    (
        "-I",
        "=/usr/include/libxml2",
    ),
    (
        "-I",
        "dir",
    ),
    (
        "-I",
        "$SYSROOT/dir",
    ),
    (
        "-isystem",
        "/usr/include/mozjs-68",
    ),
    (
        "-include",
        "/usr/include/mozjs-68/RequiredDefines.h",
    ),
    (
        "-framework",
        "Chocolate",
    ),
    (
        "-x",
        "c",
    ),
    ("-v",),
)


BAD_COMPILER_FLAGS = (
    ("-D@X",),
    ("-D-X",),
    ("-Ufoo=bar",),
    ("-F@dir",),
    ("-F-dir",),
    ("-I@dir",),
    ("-I-dir",),
    ("-O@1",),
    ("-Wa,-foo",),
    ("-W@foo",),
    ("-Wp,-DX,-D@X",),
    ("-Wp,-UX,-U@X",),
    ("-g@gdb",),
    ("-g-gdb",),
    ("-march=@dawn",),
    ("-march=-dawn",),
    ("-std=@c99",),
    ("-std=-c99",),
    ("-x@c",),
    ("-x-c",),
    (
        "-D",
        "@foo",
    ),
    (
        "-D",
        "-foo",
    ),
    (
        "-I",
        "@foo",
    ),
    (
        "-I",
        "-foo",
    ),
    (
        "-I",
        "=@obj",
    ),
    (
        "-include",
        "@foo",
    ),
    (
        "-framework",
        "-Caffeine",
    ),
    (
        "-framework",
        "@Home",
    ),
    (
        "-x",
        "--c",
    ),
    (
        "-x",
        "@obj",
    ),
)

GOOD_LINKER_FLAGS = (
    ("-Fbar",),
    ("-lbar",),
    ("-Lbar",),
    ("-fpic",),
    ("-fno-pic",),
    ("-fPIC",),
    ("-fno-PIC",),
    ("-fpie",),
    ("-fno-pie",),
    ("-fPIE",),
    ("-fno-PIE",),
    ("-fsanitize=hands",),
    ("-g",),
    ("-ggdb",),
    ("-march=souza",),
    ("-mcpu=123",),
    ("-mfpu=123",),
    ("-mtune=happybirthday",),
    ("-pic",),
    ("-pthread",),
    ("-Wl,--hash-style=both",),
    ("-Wl,-rpath,foo",),
    ("-Wl,-rpath,$ORIGIN/foo",),
    (
        "-Wl,-R",
        "/foo",
    ),
    (
        "-Wl,-R",
        "foo",
    ),
    ("-Wl,-R,foo",),
    ("-Wl,--just-symbols=foo",),
    ("-Wl,--just-symbols,foo",),
    ("-Wl,--warn-error",),
    ("-Wl,--no-warn-error",),
    ("foo.so",),
    ("_世界.dll",),
    ("./x.o",),
    ("libcgosotest.dylib",),
    (
        "-F",
        "framework",
    ),
    (
        "-l",
        ".",
    ),
    (
        "-l",
        "/etc/passwd",
    ),
    (
        "-l",
        "世界",
    ),
    (
        "-L",
        "framework",
    ),
    (
        "-framework",
        "Chocolate",
    ),
    ("-v",),
    ("-Wl,-sectcreate,__TEXT,__info_plist,${SRCDIR}/Info.plist",),
    (
        "-Wl,-framework",
        "-Wl,Chocolate",
    ),
    ("-Wl,-framework,Chocolate",),
    ("-Wl,-unresolved-symbols=ignore-all",),
    ("libcgotbdtest.tbd",),
    ("./libcgotbdtest.tbd",),
)

BAD_LINKER_FLAGS = (
    ("-DFOO",),
    ("-Dfoo=bar",),
    ("-W",),
    ("-Wall",),
    ("-fobjc-arc",),
    ("-fno-objc-arc",),
    ("-fomit-frame-pointer",),
    ("-fno-omit-frame-pointer",),
    ("-fsplit-stack",),
    ("-fno-split-stack",),
    ("-fstack-xxx",),
    ("-fno-stack-xxx",),
    ("-mstack-overflow",),
    ("-mno-stack-overflow",),
    ("-mnop-fun-dllimport",),
    ("-std=c99",),
    ("-xc",),
    (
        "-D",
        "FOO",
    ),
    (
        "-D",
        "foo=bar",
    ),
    (
        "-I",
        "FOO",
    ),
    (
        "-L",
        "@foo",
    ),
    (
        "-L",
        "-foo",
    ),
    (
        "-x",
        "c",
    ),
    ("-D@X",),
    ("-D-X",),
    ("-I@dir",),
    ("-I-dir",),
    ("-O@1",),
    ("-Wa,-foo",),
    ("-W@foo",),
    ("-g@gdb",),
    ("-g-gdb",),
    ("-march=@dawn",),
    ("-march=-dawn",),
    ("-std=@c99",),
    ("-std=-c99",),
    ("-x@c",),
    ("-x-c",),
    (
        "-D",
        "@foo",
    ),
    (
        "-D",
        "-foo",
    ),
    (
        "-I",
        "@foo",
    ),
    (
        "-I",
        "-foo",
    ),
    (
        "-l",
        "@foo",
    ),
    (
        "-l",
        "-foo",
    ),
    (
        "-framework",
        "-Caffeine",
    ),
    (
        "-framework",
        "@Home",
    ),
    ("-Wl,-framework,-Caffeine",),
    (
        "-Wl,-framework",
        "-Wl,@Home",
    ),
    (
        "-Wl,-framework",
        "@Home",
    ),
    ("-Wl,-framework,Chocolate,@Home",),
    ("-Wl,--hash-style=foo",),
    (
        "-x",
        "--c",
    ),
    (
        "-x",
        "@obj",
    ),
    ("-Wl,-rpath,@foo",),
    ("-Wl,-R,foo,bar",),
    ("-Wl,-R,@foo",),
    ("-Wl,--just-symbols,@foo",),
    ("../x.o",),
)


def test_good_compiler_flags() -> None:
    for flags in GOOD_COMPILER_FLAGS:
        check_compiler_flags(flags, "test")


def test_bad_compiler_flags() -> None:
    for flags in BAD_COMPILER_FLAGS:
        with pytest.raises(CGoFlagSecurityError):
            check_compiler_flags(flags, "test")


def test_good_linker_flags() -> None:
    for flags in GOOD_LINKER_FLAGS:
        check_linker_flags(flags, "test")


def test_bad_linker_flags() -> None:
    for flags in BAD_LINKER_FLAGS:
        with pytest.raises(CGoFlagSecurityError):
            check_linker_flags(flags, "test")
