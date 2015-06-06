# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
import tempfile
from contextlib import contextmanager

from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from twitter.common.collections import OrderedSet

from pants.backend.core.tasks.task import Task
from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.python_chroot import PythonChroot
from pants.backend.python.python_setup import PythonRepos, PythonSetup
from pants.base import hash_utils
from pants.base.exceptions import TaskError


class PythonTask(Task):
  # If needed, we set this as the executable entry point of any chroots we create.
  CHROOT_EXECUTABLE_NAME = '__pants_executable__'

  @classmethod
  def global_subsystems(cls):
    return super(PythonTask, cls).global_subsystems() + (PythonSetup, PythonRepos)

  def __init__(self, *args, **kwargs):
    super(PythonTask, self).__init__(*args, **kwargs)
    self._compatibilities = self.get_options().interpreter or [b'']
    self._interpreter_cache = None
    self._interpreter = None

  @property
  def interpreter_cache(self):
    if self._interpreter_cache is None:
      self._interpreter_cache = PythonInterpreterCache(PythonSetup.global_instance(),
                                                       PythonRepos.global_instance(),
                                                       logger=self.context.log.debug)

      # Cache setup's requirement fetching can hang if run concurrently by another pants proc.
      self.context.acquire_lock()
      try:
        # We pass in filters=compatibilities because setting up some python versions
        # (e.g., 3<=python<3.3) crashes, and this gives us an escape hatch.
        self._interpreter_cache.setup(filters=self._compatibilities)
      finally:
        self.context.release_lock()
    return self._interpreter_cache

  @property
  def interpreter(self):
    """Subclasses can use this if they're fine with the default interpreter (the usual case)."""
    if self._interpreter is None:
      self._interpreter = self.select_interpreter(self._compatibilities)
    return self._interpreter

  def select_interpreter_for_targets(self, targets):
    """Pick an interpreter compatible with all the specified targets."""
    allowed_interpreters = OrderedSet(self.interpreter_cache.interpreters)
    targets_with_compatibilities = []  # Used only for error messages.

    # Constrain allowed_interpreters based on each target's compatibility requirements.
    for target in targets:
      if target.is_python and hasattr(target, 'compatibility') and target.compatibility:
        targets_with_compatibilities.append(target)
        compatible_with_target = list(self.interpreter_cache.matches(target.compatibility))
        allowed_interpreters &= compatible_with_target

    if not allowed_interpreters:
      # Create a helpful error message.
      unique_compatibilities = set(tuple(t.compatibility) for t in targets_with_compatibilities)
      unique_compatibilities_strs = [','.join(x) for x in unique_compatibilities if x]
      targets_with_compatibilities_strs = [str(t) for t in targets_with_compatibilities]
      raise TaskError('Unable to detect a suitable interpreter for compatibilities: {} '
                      '(Conflicting targets: {})'.format(' && '.join(unique_compatibilities_strs),
                                                         ', '.join(targets_with_compatibilities_strs)))

    # Return the lowest compatible interpreter.
    return self.interpreter_cache.select_interpreter(allowed_interpreters)[0]

  def select_interpreter(self, filters):
    """Subclasses can use this to be more specific about interpreter selection."""
    interpreters = self.interpreter_cache.select_interpreter(
      list(self.interpreter_cache.matches(filters)))
    if len(interpreters) != 1:
      raise TaskError('Unable to detect a suitable interpreter.')
    interpreter = interpreters[0]
    self.context.log.debug('Selected {}'.format(interpreter))
    return interpreter

  @property
  def chroot_cache_dir(self):
    return PythonSetup.global_instance().chroot_cache_dir

  @contextmanager
  def cached_chroot(self, interpreter, pex_info, targets, platforms,
                    extra_requirements=None, executable_file_content=None):
    """Returns a cached PythonChroot created with the specified args.

    The returned chroot will be cached for future use.

    TODO: Garbage-collect old chroots, so they don't pile up?
    """
    # This PexInfo contains any customizations specified by the caller.
    # The process of building a pex modifies it further.
    pex_info = pex_info or PexInfo.default()

    path = self._chroot_path(PythonSetup.global_instance(), interpreter, pex_info, targets,
                             platforms, extra_requirements, executable_file_content)
    if not os.path.exists(path):
      path_tmp = path + '.tmp'
      self._build_chroot(path_tmp, interpreter, pex_info, targets, platforms,
                         extra_requirements, executable_file_content)
      shutil.move(path_tmp, path)

    # We must read the PexInfo that was frozen into the pex, so we get the modifications
    # created when that pex was built.
    pex_info = PexInfo.from_pex(path)
    # Now create a PythonChroot wrapper without dumping it.
    builder = PEXBuilder(path=path, interpreter=interpreter, pex_info=pex_info)
    chroot = PythonChroot(
      context=self.context,
      python_setup=PythonSetup.global_instance(),
      python_repos=PythonRepos.global_instance(),
      interpreter=interpreter,
      builder=builder,
      targets=targets,
      platforms=platforms,
      extra_requirements=extra_requirements)
    # TODO: Doesn't really need to be a contextmanager, but it's convenient to make it so
    # while transitioning calls to temporary_chroot to calls to cached_chroot.
    # We can revisit after that transition is complete.
    yield chroot

  @contextmanager
  def temporary_chroot(self, interpreter, pex_info, targets, platforms,
                       extra_requirements=None, executable_file_content=None):
    path = tempfile.mkdtemp()
    pex_info = pex_info or PexInfo.default()
    chroot = self._build_chroot(path, interpreter, pex_info, targets, platforms,
                                extra_requirements, executable_file_content)
    yield chroot
    chroot.delete()

  def _build_chroot(self, path, interpreter, pex_info, targets, platforms,
                     extra_requirements=None, executable_file_content=None):
    """Create a PythonChroot with the specified args."""
    builder = PEXBuilder(path=path, interpreter=interpreter, pex_info=pex_info)
    with self.context.new_workunit('chroot'):
      chroot = PythonChroot(
        context=self.context,
        python_setup=PythonSetup.global_instance(),
        python_repos=PythonRepos.global_instance(),
        interpreter=interpreter,
        builder=builder,
        targets=targets,
        platforms=platforms,
        extra_requirements=extra_requirements)
      chroot.dump()
      if executable_file_content is not None:
        with open(os.path.join(path, '{}.py'.format(self.CHROOT_EXECUTABLE_NAME)), 'w') as outfile:
          outfile.write(executable_file_content)
        # Override any user-specified entry point, under the assumption that the
        # executable_file_content does what the user intends (including, probably, calling that
        # underlying entry point).
        pex_info.entry_point = self.CHROOT_EXECUTABLE_NAME
      builder.freeze()
    return chroot

  def _chroot_path(self, python_setup, interpreter, pex_info, targets, platforms,
                   extra_requirements, executable_file_content):
    """Pick a unique, well-known directory name for the chroot with the specified parameters.

    TODO: How many of these do we expect to have? Currently they are all under a single
    directory, and some filesystems (E.g., HFS+) don't handle directories with thousands of
    entries well. GC'ing old chroots may be enough of a solution, assuming this is even a problem.
    """
    fingerprint_components = [str(interpreter.identity)]
    if pex_info:
      fingerprint_components.append(pex_info.dump())
    fingerprint_components.extend(filter(None, [t.payload.fingerprint() for t in targets]))
    if platforms:
      fingerprint_components.extend(platforms)
    if extra_requirements:
      fingerprint_components.extend([r.cache_key() for r in extra_requirements])
    if executable_file_content is not None:
      fingerprint_components.append(executable_file_content)

    fingerprint = hash_utils.hash_all(fingerprint_components)
    return os.path.join(python_setup.chroot_cache_dir, fingerprint)
