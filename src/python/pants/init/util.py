# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from typing import cast

from pants.base.build_environment import get_buildroot
from pants.fs.fs import safe_filename_from_path
from pants.goal.goal import Goal
from pants.init.options_initializer import BuildConfigInitializer
from pants.option.option_value_container import OptionValueContainer
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import absolute_symlink, safe_mkdir, safe_rmtree, symlink_is_correct

SOURCE_CONTROL_DIRS = (".git", ".hg", ".svn")


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

    def maybe_create_source_control_symlink():
        """If the buildroot we are working in has a source control administrative directory, we need
        to add a link to it from the physical workdir we create.

        Tools which run from the physical workdir expect to be able to glean repository information
        directly. For instance node_binary targets are built using ad-hoc build scripts which can do
        this.
        """
        # Don't link anything unless this option is enabled.
        if not global_options.pants_physical_workdir_source_control:
            return
        for scm_state_dir in SOURCE_CONTROL_DIRS:
            scm_source_path = os.path.join(get_buildroot(), scm_state_dir)
            scm_target_path = os.path.join(workdir_dst, scm_state_dir)
            if os.path.exists(scm_source_path) and not symlink_is_correct(
                scm_source_path, scm_target_path
            ):
                absolute_symlink(scm_source_path, scm_target_path)
                break

    def create_symlink_to_clean_workdir():
        # Executed when no link exists. We treat this as equivalent to a request to have deleted
        # this state. Operations like `clean-all` will already have purged the destination, but in
        # cases like manual removal of the symlink, we want to treat the case as equivalent.
        safe_mkdir(workdir_dst, clean=True)
        absolute_symlink(workdir_dst, workdir_src)
        maybe_create_source_control_symlink()

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
            maybe_create_source_control_symlink()
    else:
        # Remove existing physical workdir (.pants.d dir)
        safe_rmtree(workdir_src)
        # Create both symlink workdir (.pants.d dir) and its destination/physical workdir.
        create_symlink_to_clean_workdir()
    return workdir_src


def clean_global_runtime_state(reset_subsystem=False):
    """Resets the global runtime state of a pants runtime for cleaner forking.

    :param bool reset_subsystem: Whether or not to clean Subsystem global state.
    """
    if reset_subsystem:
        # Reset subsystem state.
        Subsystem.reset()

    # Reset Goals and Tasks.
    Goal.clear()

    # Reset global plugin state.
    BuildConfigInitializer.reset()
