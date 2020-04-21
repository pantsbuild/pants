# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import shutil
from collections import defaultdict
from textwrap import dedent

from pex.interpreter import PythonInterpreter

from pants.backend.python.targets.python_target import PythonTarget
from pants.base.exceptions import TaskError
from pants.process.lock import OwnerPrintingInterProcessFileLock
from pants.python.python_setup import PythonSetup
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import safe_concurrent_creation, safe_mkdir
from pants.util.memo import memoized_property

logger = logging.getLogger(__name__)


# TODO: Move under subsystems/ .
class PythonInterpreterCache(Subsystem):
    """Finds Python interpreters on the local system."""

    options_scope = "python-interpreter-cache"

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (PythonSetup,)

    class UnsatisfiableInterpreterConstraintsError(TaskError):
        """Indicates a Python interpreter matching given constraints could not be located."""

    @staticmethod
    def _matches(interpreter, filters=()):
        return not filters or any(interpreter.identity.matches(filt) for filt in filters)

    @classmethod
    def _matching(cls, interpreters, filters=()):
        for interpreter in interpreters:
            if cls._matches(interpreter, filters=filters):
                yield interpreter

    @property
    def python_setup(self):
        return PythonSetup.global_instance()

    @memoized_property
    def _cache_dir(self):
        cache_dir = self.python_setup.interpreter_cache_dir
        safe_mkdir(cache_dir)
        return cache_dir

    def partition_targets_by_compatibility(self, targets):
        """Partition targets by their compatibility constraints.

        :param targets: a list of `PythonTarget` objects
        :returns: (tgts_by_compatibilities, filters): a dict that maps compatibility constraints
          to a list of matching targets, the aggregate set of compatibility constraints imposed
          by the target set
        :rtype: (dict(str, list), set)
        """
        tgts_by_compatibilities = defaultdict(list)
        filters = set()

        for target in targets:
            if isinstance(target, PythonTarget):
                c = self.python_setup.compatibility_or_constraints(target.compatibility)
                tgts_by_compatibilities[c].append(target)
                filters.update(c)
        return tgts_by_compatibilities, filters

    def select_interpreter_for_targets(self, targets):
        """Pick an interpreter compatible with all the specified targets."""

        tgts_by_compatibilities, total_filter_set = self.partition_targets_by_compatibility(targets)
        allowed_interpreters = set(self.setup(filters=total_filter_set))

        # Constrain allowed_interpreters based on each target's compatibility requirements.
        for compatibility in tgts_by_compatibilities:
            compatible_with_target = set(self._matching(allowed_interpreters, compatibility))
            allowed_interpreters &= compatible_with_target

        if not allowed_interpreters:
            # Create a helpful error message.
            all_interpreter_version_strings = sorted(
                {
                    interpreter.version_string
                    # NB: self.setup() requires filters to be passed, or else it will use the global interpreter
                    # constraints. We allow any interpreter other than CPython 3.0-3.3, which is known to choke
                    # with Pants.
                    for interpreter in self.setup(filters=("CPython<3", "CPython>=3.3", "PyPy"))
                }
            )
            unique_compatibilities = {tuple(c) for c in tgts_by_compatibilities.keys()}
            unique_compatibilities_strs = [",".join(x) for x in unique_compatibilities if x]
            tgts_by_compatibilities_strs = [
                t[0].address.spec for t in tgts_by_compatibilities.values()
            ]
            raise self.UnsatisfiableInterpreterConstraintsError(
                dedent(
                    """\
                    Unable to detect a suitable interpreter for compatibilities: {} (Conflicting targets: {})
            
                    Pants detected these interpreter versions on your system: {}
            
                    Possible ways to fix this:
                    * Modify your Python interpreter constraints by following https://www.pantsbuild.org/python_readme.html#configure-the-python-version.
                    * Ensure the targeted Python version is installed and discoverable.
                    * Modify Pants' interpreter search paths via --python-setup-interpreter-search-paths.""".format(
                        " && ".join(sorted(unique_compatibilities_strs)),
                        ", ".join(tgts_by_compatibilities_strs),
                        ", ".join(all_interpreter_version_strings),
                    )
                )
            )
        # Return the lowest compatible interpreter.
        return min(allowed_interpreters)

    def _interpreter_from_relpath(self, path, filters=()):
        path = os.path.join(self._cache_dir, path)
        try:
            executable = os.readlink(os.path.join(path, "python"))
            if not os.path.exists(executable):
                self._purge_interpreter(path)
                return None
        except OSError:
            return None
        interpreter = PythonInterpreter.from_binary(executable)
        if self._matches(interpreter, filters=filters):
            return interpreter
        return None

    def _setup_interpreter(self, interpreter, identity_str):
        cache_target_path = os.path.join(self._cache_dir, identity_str)
        with safe_concurrent_creation(cache_target_path) as safe_path:
            os.mkdir(
                safe_path
            )  # Parent will already have been created by safe_concurrent_creation.
            os.symlink(interpreter.binary, os.path.join(safe_path, "python"))
            return interpreter

    def _setup_cached(self, filters=()):
        """Find all currently-cached interpreters."""
        for interpreter_dir in os.listdir(self._cache_dir):
            pi = self._interpreter_from_relpath(interpreter_dir, filters=filters)
            if pi:
                logger.debug(f"Detected interpreter {pi.binary}: {pi.identity}")
                yield pi

    def _setup_paths(self, paths, filters=()):
        """Find interpreters under paths, and cache them."""
        for interpreter in self._matching(PythonInterpreter.all(paths), filters=filters):
            identity_str = str(interpreter.identity)
            pi = self._interpreter_from_relpath(identity_str, filters=filters)
            if pi is None:
                self._setup_interpreter(interpreter, identity_str)
                pi = self._interpreter_from_relpath(identity_str, filters=filters)
            if pi:
                yield pi

    def setup(self, filters=()):
        """Sets up a cache of python interpreters.

        :param filters: A sequence of strings that constrain the interpreter compatibility for this
          cache, using the Requirement-style format, e.g. ``'CPython>=3', or just ['>=2.7','<3']``
          for requirements agnostic to interpreter class.
        :returns: A list of cached interpreters
        :rtype: list of :class:`pex.interpreter.PythonInterpreter`
        """
        # We filter the interpreter cache itself (and not just the interpreters we pull from it)
        # because setting up some python versions (e.g., 3<=python<3.3) crashes, and this gives us
        # an escape hatch.
        filters = filters if any(filters) else self.python_setup.interpreter_constraints
        setup_paths = self.python_setup.interpreter_search_paths
        logger.debug(
            f"Initializing Python interpreter cache matching filters `{':'.join(filters)}` "
            f"from paths `{':'.join(setup_paths)}`"
        )
        interpreters = []

        def unsatisfied_filters():
            return [f for f in filters if len(list(self._matching(interpreters, [f]))) == 0]

        with OwnerPrintingInterProcessFileLock(path=os.path.join(self._cache_dir, ".file_lock")):
            interpreters.extend(self._setup_cached(filters=filters))
            if not interpreters or unsatisfied_filters():
                interpreters.extend(self._setup_paths(setup_paths, filters=filters))

        for filt in unsatisfied_filters():
            logger.debug(f"No valid interpreters found for {filt}!")

        matches = list(self._matching(interpreters, filters=filters))
        if len(matches) == 0:
            logger.debug("Found no valid interpreters!")

        logger.debug(
            "Initialized Python interpreter cache with {}".format(
                ", ".join([x.binary for x in matches])
            )
        )
        return matches

    def _purge_interpreter(self, interpreter_dir):
        try:
            logger.info(
                f"Detected stale interpreter `{interpreter_dir}` in the interpreter cache, "
                f"purging."
            )
            shutil.rmtree(interpreter_dir, ignore_errors=True)
        except Exception as e:
            logger.warning(
                f"Caught exception {e!r} during interpreter purge. "
                f"Please run `{self.get_options().pants_bin_name} clean-all`!"
            )
