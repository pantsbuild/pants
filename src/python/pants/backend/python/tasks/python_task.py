# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
import shutil
import tempfile
from contextlib import contextmanager

from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo

from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.python_chroot import PythonChroot
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.base import hash_utils
from pants.binaries.thrift_binary import ThriftBinary
from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.python.python_repos import PythonRepos
from pants.task.task import Task


class PythonTask(Task):
  # If needed, we set this as the executable entry point of any chroots we create.
  CHROOT_EXECUTABLE_NAME = '__pants_executable__'

  @classmethod
  def implementation_version(cls):
    return super(PythonTask, cls).implementation_version() + [('PythonTask', 1)]

  @classmethod
  def subsystem_dependencies(cls):
    return (super(PythonTask, cls).subsystem_dependencies() +
            (IvySubsystem, PythonSetup, PythonRepos, ThriftBinary.Factory.scoped(cls)))

  def __init__(self, *args, **kwargs):
    super(PythonTask, self).__init__(*args, **kwargs)
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
        self._interpreter_cache.setup()
      finally:
        self.context.release_lock()
    return self._interpreter_cache

  def select_interpreter_for_targets(self, targets):
    """Pick an interpreter compatible with all the specified targets."""
    return self.interpreter_cache.select_interpreter_for_targets(targets)

  @property
  def chroot_cache_dir(self):
    return PythonSetup.global_instance().chroot_cache_dir

  @property
  def ivy_bootstrapper(self):
    return Bootstrapper(ivy_subsystem=IvySubsystem.global_instance())

  @property
  def thrift_binary_factory(self):
    return ThriftBinary.Factory.scoped_instance(self).create

  def create_chroot(self, interpreter, builder, targets, platforms, extra_requirements):
    return PythonChroot(python_setup=PythonSetup.global_instance(),
                        python_repos=PythonRepos.global_instance(),
                        ivy_bootstrapper=self.ivy_bootstrapper,
                        thrift_binary_factory=self.thrift_binary_factory,
                        interpreter=interpreter,
                        builder=builder,
                        targets=targets,
                        platforms=platforms,
                        extra_requirements=extra_requirements,
                        log=self.context.log)

  def cached_chroot(self, interpreter, pex_info, targets, platforms=None,
                    extra_requirements=None, executable_file_content=None):
    """Returns a cached PythonChroot created with the specified args.

    The returned chroot will be cached for future use.

    :rtype: pants.backend.python.python_chroot.PythonChroot

    TODO: Garbage-collect old chroots, so they don't pile up?
    TODO: Ideally chroots would just be products produced by some other task. But that's
          a bit too complicated to implement right now, as we'd need a way to request
          chroots for a variety of sets of targets.
    """
    # This PexInfo contains any customizations specified by the caller.
    # The process of building a pex modifies it further.
    pex_info = pex_info or PexInfo.default()

    path = self._chroot_path(interpreter, pex_info, targets, platforms, extra_requirements,
                             executable_file_content)
    if not os.path.exists(path):
      path_tmp = path + '.tmp'
      self._build_chroot(path_tmp, interpreter, pex_info, targets, platforms,
                         extra_requirements, executable_file_content)
      shutil.move(path_tmp, path)

    # We must read the PexInfo that was frozen into the pex, so we get the modifications
    # created when that pex was built.
    pex_info = PexInfo.from_pex(path)
    # Now create a PythonChroot wrapper without dumping it.
    builder = PEXBuilder(path=path, interpreter=interpreter, pex_info=pex_info, copy=True)
    return self.create_chroot(interpreter=interpreter,
                              builder=builder,
                              targets=targets,
                              platforms=platforms,
                              extra_requirements=extra_requirements)

  @contextmanager
  def temporary_chroot(self, interpreter, pex_info, targets, platforms,
                       extra_requirements=None, executable_file_content=None):
    path = tempfile.mkdtemp()  # Not a contextmanager: chroot.delete() will clean this up anyway.
    pex_info = pex_info or PexInfo.default()
    chroot = self._build_chroot(path, interpreter, pex_info, targets, platforms,
                                extra_requirements, executable_file_content)
    yield chroot
    chroot.delete()

  def _build_chroot(self, path, interpreter, pex_info, targets, platforms,
                     extra_requirements=None, executable_file_content=None):
    """Create a PythonChroot with the specified args."""
    builder = PEXBuilder(path=path, interpreter=interpreter, pex_info=pex_info, copy=True)
    with self.context.new_workunit('chroot'):
      chroot = self.create_chroot(
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

  def _chroot_path(self, interpreter, pex_info, targets, platforms, extra_requirements,
                   executable_file_content):
    """Pick a unique, well-known directory name for the chroot with the specified parameters.

    TODO: How many of these do we expect to have? Currently they are all under a single
    directory, and some filesystems (E.g., HFS+) don't handle directories with thousands of
    entries well. GC'ing old chroots may be enough of a solution, assuming this is even a problem.
    """
    fingerprint_components = [str(interpreter.identity)]

    if pex_info:
      # TODO(John Sirois): When https://rbcommons.com/s/twitter/r/2517/ lands, leverage the dump
      # **kwargs to sort keys or else find some other better way to get a stable fingerprint of
      # PexInfo.
      fingerprint_components.append(json.dumps(json.loads(pex_info.dump()), sort_keys=True))

    fingerprint_components.extend(sorted(t.transitive_invalidation_hash() for t in set(targets)))

    if platforms:
      fingerprint_components.extend(sorted(set(platforms)))

    if extra_requirements:
      # TODO(John Sirois): The extras should be uniqified before fingerprinting, but
      # PythonRequirement arguably does not have a proper __eq__.  For now we lean on the cache_key
      # of unique PythonRequirement being unique - which is probably good enough (the cache key is
      # narrower than the full scope of PythonRequirement attributes at present, thus the hedge).
      fingerprint_components.extend(sorted(set(r.cache_key() for r in extra_requirements)))

    if executable_file_content is not None:
      fingerprint_components.append(executable_file_content)

    fingerprint = hash_utils.hash_all(fingerprint_components)
    return os.path.join(self.chroot_cache_dir, fingerprint)
