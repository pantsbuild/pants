# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import errno
import os
import random
import shutil
from contextlib import contextmanager
from typing import Callable, Dict, Iterator, Sequence
from uuid import uuid4

from pants.util.contextutil import temporary_file


def atomic_copy(src: str, dst: str) -> None:
    """Copy the file src to dst, overwriting dst atomically."""
    with temporary_file(root_dir=os.path.dirname(dst)) as tmp_dst:
        shutil.copyfile(src, tmp_dst.name)
        os.chmod(tmp_dst.name, os.stat(src).st_mode)
        os.rename(tmp_dst.name, dst)


@contextmanager
def safe_temp_edit(filename: str) -> Iterator[str]:
    """Safely modify a file within context that automatically reverts any changes afterwards.

    The file mutatation occurs in place. The file is backed up in a temporary file before edits
    occur and when the context is closed, the mutated file is discarded and replaced with the backup.

    WARNING: There may be a chance that the file may not be restored and this method should be used
    carefully with the known risk.
    """
    with temporary_file() as tmp_file:
        try:
            shutil.copyfile(filename, tmp_file.name)
            yield filename
        finally:
            shutil.copyfile(tmp_file.name, filename)


def create_size_estimators() -> Dict[str, Callable[[Sequence[str]], int]]:
    """Create a dict of name to a function that returns an estimated size for a given target.

    The estimated size is used to build the largest targets first (subject to dependency constraints).
    Choose 'random' to choose random sizes for each target, which may be useful for distributed
    builds.
    :returns: Dict of a name to a function that returns an estimated size.
    """

    def line_count(filename: str) -> int:
        with open(filename, "rb") as fh:
            return sum(1 for line in fh)

    return {
        "linecount": lambda srcs: sum(line_count(src) for src in srcs),
        "filecount": lambda srcs: len(srcs),
        "filesize": lambda srcs: sum(os.path.getsize(src) for src in srcs),
        "nosize": lambda srcs: 0,
        "random": lambda srcs: random.randint(0, 10000),
    }


def safe_hardlink_or_copy(source: str, dest: str, overwrite: bool = False) -> None:
    def do_copy() -> None:
        temp_dest = dest + uuid4().hex
        shutil.copyfile(source, temp_dest)
        os.rename(temp_dest, dest)

    try:
        os.link(source, dest)
    except OSError as e:
        if e.errno == errno.EEXIST:
            # File already exists.  If overwrite=True, write otherwise skip.
            if overwrite:
                do_copy()
        elif e.errno == errno.EXDEV:
            # Hard link across devices, fall back on copying
            do_copy()
        else:
            raise
