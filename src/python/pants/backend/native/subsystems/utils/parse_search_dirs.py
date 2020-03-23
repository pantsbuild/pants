# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import re
import subprocess

from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import is_readable_dir
from pants.util.memo import memoized_classproperty
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import safe_shlex_join

logger = logging.getLogger(__name__)


class ParseSearchDirs(Subsystem):
    """Parse the output of invoking a compiler with the '-print-search-dirs' argument for lib dirs.

    This is used to expose resources from one compiler (e.g. a compiler preinstalled on the host
    which has knowledge of distro-maintained system libraries such as libc) to the compilers/linkers
    that Pants provides. This is also used to share resources between different :class:`BinaryTool`s
    with compiler executables.
    """

    options_scope = "parse-search-dirs"

    class ParseSearchDirsError(Exception):
        pass

    @memoized_classproperty
    def _search_dirs_libraries_regex(cls):
        return re.compile("^libraries: =(.*)$", flags=re.MULTILINE)

    def _invoke_compiler_exe(self, cmd, env):
        try:
            # Get stderr interspersed in the error message too -- this should not affect output parsing.
            compiler_output = subprocess.check_output(
                cmd, env=env, stderr=subprocess.STDOUT
            ).decode()
        except OSError as e:
            # We use `safe_shlex_join` here to pretty-print the command.
            raise self.ParseSearchDirsError(
                "Process invocation with argv '{}' and environment {!r} failed.".format(
                    safe_shlex_join(cmd), env
                ),
                e,
            )
        except subprocess.CalledProcessError as e:
            raise self.ParseSearchDirsError(
                "Process invocation with argv '{}' and environment {!r} exited with non-zero code {}. "
                "output:\n{}".format(safe_shlex_join(cmd), env, e.returncode, e.output),
                e,
            )

        return compiler_output

    def _parse_libraries_from_compiler_search_dirs(self, compiler_exe, env):
        # This argument is supported by at least gcc and clang.
        cmd = [compiler_exe, "-print-search-dirs"]

        compiler_output = self._invoke_compiler_exe(cmd, env)

        libs_line = self._search_dirs_libraries_regex.search(compiler_output)
        if not libs_line:
            raise self.ParseSearchDirsError(
                "Could not parse libraries from output of {!r}:\n{}".format(
                    safe_shlex_join(cmd), compiler_output
                )
            )
        return libs_line.group(1).split(":")

    def _filter_existing_dirs(self, dir_candidates, compiler_exe):
        real_dirs = OrderedSet()

        for maybe_existing_dir in dir_candidates:
            # Could use a `seen_dir_paths` set if we want to avoid pinging the fs for duplicate entries.
            if is_readable_dir(maybe_existing_dir):
                real_dirs.add(os.path.realpath(maybe_existing_dir))
            else:
                logger.debug(
                    "non-existent or non-accessible directory at {} while "
                    "parsing directories from {}".format(maybe_existing_dir, compiler_exe)
                )

        return list(real_dirs)

    def get_compiler_library_dirs(self, compiler_exe, env=None):
        all_dir_candidates = self._parse_libraries_from_compiler_search_dirs(compiler_exe, env=env)
        return self._filter_existing_dirs(all_dir_candidates, compiler_exe)
