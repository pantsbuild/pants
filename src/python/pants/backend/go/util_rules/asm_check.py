# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys

# Script that checks whether the files passed on the command line looks like they could be
# Golang-format assembly language files.
#
# This is used by the cgo rules as a heuristic to determine if the user is passing Golang assembly
# format instead of gcc assembly format.


def maybe_is_golang_assembly(data: bytes) -> bool:
    return (
        data.startswith(b"TEXT")
        or b"\nTEXT" in data
        or data.startswith(b"DATA")
        or b"\nDATA" in data
        or data.startswith(b"GLOBL")
        or b"\nGLOBL" in data
    )


def main(args):
    for arg in args:
        with open(arg, "rb") as f:
            data = f.read()
        if maybe_is_golang_assembly(data):
            print(f"{arg}")


if __name__ == "__main__":
    main(sys.argv[1:])
