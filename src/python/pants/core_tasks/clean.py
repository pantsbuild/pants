# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os

from pants.task.task import Task
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_concurrent_rename, safe_rmtree

logger = logging.getLogger(__name__)


class Clean(Task):
    """Delete all build products, creating a clean workspace.

    The clean-all method allows for both synchronous and asynchronous options with the --async
    option.
    """

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--async",
            type=bool,
            default=False,
            help="Allows clean-all to run in the background. Can dramatically speed up clean-all "
            "for large pants workdirs.",
        )

    def execute(self):
        pants_wd = self.get_options().pants_workdir
        if self.get_options().pants_physical_workdir_base:
            # If a physical workdir is in use, operate on it rather than on the symlink that points to it.
            pants_wd = os.readlink(pants_wd)
        pants_trash = os.path.join(pants_wd, "trash")

        # Creates, and eventually deletes, trash dir created in .pants_cleanall.
        with temporary_dir(
            cleanup=False, root_dir=os.path.dirname(pants_wd), prefix=".pants_cleanall"
        ) as tmpdir:
            logger.debug(f"Moving trash to {tmpdir} for deletion")

            tmp_trash = os.path.join(tmpdir, "trash")

            # Moves contents of .pants.d to cleanup dir.
            safe_concurrent_rename(pants_wd, tmp_trash)
            safe_concurrent_rename(tmpdir, pants_wd)

            if self.get_options()["async"]:
                # The trash directory is deleted in a child process.
                pid = os.fork()
                if pid == 0:
                    try:
                        safe_rmtree(pants_trash)
                    except (IOError, OSError):
                        logger.warning("Async clean-all failed. Please try again.")
                    finally:
                        os._exit(0)
                else:
                    logger.debug(f"Forked an asynchronous clean-all worker at pid: {pid}")
            else:
                # Recursively removes pants cache; user waits patiently.
                logger.info(
                    f"For async removal, run"
                    f" `{self.get_options().pants_bin_name} clean-all --async`"
                )
                safe_rmtree(pants_trash)
