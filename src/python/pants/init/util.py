# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from typing import cast

from pants.fs.fs import safe_filename_from_path
from pants.init.options_initializer import BuildConfigInitializer
from pants.option.option_value_container import OptionValueContainer
from pants.option.subsystem import Subsystem
from pants.util.dirutil import absolute_symlink, safe_mkdir, safe_rmtree


def init_workdir(global_options: OptionValueContainer) -> str:
    """Given the bootstrap options (generally immediately after bootstrap), initialize the workdir.

    If it is in use, the "physical" workdir is a directory under the `pants_physical_workdir_base`
    that is unique to each working copy (via including the entire path to the working copy in its
    name using `safe_filename_from_path`).
    """
    workdir_src = cast(str, global_options.pants_workdir)
    if not global_options.pants_physical_workdir_base:
        safe_mkdir(workdir_src)
        return workdir_src

    workdir_base = global_options.pants_physical_workdir_base
    workdir_dst = os.path.join(workdir_base, safe_filename_from_path(workdir_src))

    def create_symlink_to_clean_workdir():
        # Executed when no link exists. We treat this as equivalent to a request to have deleted
        # this state. Operations like `clean-all` will already have purged the destination, but in
        # cases like manual removal of the symlink, we want to treat the case as equivalent.
        safe_mkdir(workdir_dst, clean=True)
        absolute_symlink(workdir_dst, workdir_src)

    if not os.path.lexists(workdir_src):
        # Does not exist.
        create_symlink_to_clean_workdir()
    elif os.path.islink(workdir_src):
        if os.readlink(workdir_src) != workdir_dst:
            # Exists but is incorrect.
            os.unlink(workdir_src)
            create_symlink_to_clean_workdir()
        else:
            # Exists and is correct: ensure that the destination exists.
            safe_mkdir(workdir_dst)
    else:
        # Remove existing physical workdir (.pants.d dir)
        safe_rmtree(workdir_src)
        # Create both symlink workdir (.pants.d dir) and its destination/physical workdir
        create_symlink_to_clean_workdir()
    return workdir_src


def clean_global_runtime_state() -> None:
    """Resets the global runtime state of a pants runtime."""

    Subsystem.reset()

    # Reset global plugin state.
    BuildConfigInitializer.reset()
