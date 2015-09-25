# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import collections
import contextlib
import multiprocessing
import os
import subprocess

from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.base.exceptions import TaskError
from pants.binaries import binary_util
from pants.util.dirutil import safe_mkdir, safe_walk


Jvmdoc = collections.namedtuple('Jvmdoc', ['tool_name', 'product_type'])


class JvmdocGen(JvmTask):

  @classmethod
  def jvmdoc(cls):
    """Subclasses should return their Jvmdoc configuration."""
    raise NotImplementedError()

  @classmethod
  def register_options(cls, register):
    super(JvmdocGen, cls).register_options(register)
    tool_name = cls.jvmdoc().tool_name

    register('--include-codegen', default=False, action='store_true',
             fingerprint=True,
             help='Create {0} for generated code.'.format(tool_name))

    register('--transitive', default=True, action='store_true',
             fingerprint=True,
             help='Create {0} for the transitive closure of internal targets reachable from the '
                  'roots specified on the command line.'.format(tool_name))

    register('--combined', default=False, action='store_true',
             fingerprint=True,
             help='Generate {0} for all targets combined, instead of each target '
                  'individually.'.format(tool_name))

    register('--open', default=False, action='store_true',
             help='Open the generated {0} in a browser (implies --combined).'.format(tool_name))

    register('--ignore-failure', default=False, action='store_true',
             fingerprint=True,
             help='Do not consider {0} errors to be build errors.'.format(tool_name))

    # TODO(John Sirois): This supports the JarPublish task and is an abstraction leak.
    # It allows folks doing a local-publish to skip an expensive and un-needed step.
    # Remove this flag and instead support conditional requirements being registered against
    # the round manager.  This may require incremental or windowed flag parsing that happens bit by
    # bit as tasks are recursively prepared vs. the current all-at once style.
    register('--skip', default=False, action='store_true',
             fingerprint=True,
             help='Skip {0} generation.'.format(tool_name))

  @classmethod
  def product_types(cls):
    return [cls.jvmdoc().product_type]

  @classmethod
  def prepare(cls, options, round_manager):
    super(JvmdocGen, cls).prepare(options, round_manager)

    # TODO(John Sirois): this is a fake requirement in order to force compile run before this
    # goal. Introduce a RuntimeClasspath product for JvmCompile and PrepareResources to populate
    # and depend on that.
    # See: https://github.com/pantsbuild/pants/issues/310
    round_manager.require_data('classes_by_target')

  def __init__(self, *args, **kwargs):
    super(JvmdocGen, self).__init__(*args, **kwargs)

    options = self.get_options()
    self._include_codegen = options.include_codegen
    self.transitive = options.transitive
    self.open = options.open
    self.combined = self.open or options.combined
    self.ignore_failure = options.ignore_failure
    self.skip = options.skip

  def generate_doc(self, language_predicate, create_jvmdoc_command):
    """
    Generate an execute method given a language predicate and command to create documentation

    language_predicate: a function that accepts a target and returns True if the target is of that
                        language
    create_jvmdoc_command: (classpath, directory, *targets) -> command (string) that will generate
                           documentation documentation for targets
    """
    if self.skip:
      return

    catalog = self.context.products.isrequired(self.jvmdoc().product_type)
    if catalog and self.combined:
      raise TaskError(
          'Cannot provide {} target mappings for combined output'.format(self.jvmdoc().product_type))

    def docable(tgt):
      return language_predicate(tgt) and (self._include_codegen or not tgt.is_codegen)

    targets = self.context.targets(predicate=docable)
    if not targets:
      return

    with self.invalidated(targets) as invalidation_check:
      safe_mkdir(self.workdir)
      classpath = self.classpath(targets)

      def find_jvmdoc_targets():
        invalid_targets = set()
        for vt in invalidation_check.invalid_vts:
          invalid_targets.update(vt.targets)

        if self.transitive:
          return invalid_targets
        else:
          return set(invalid_targets).intersection(set(self.context.target_roots))

      jvmdoc_targets = list(find_jvmdoc_targets())
      if self.combined:
        self._generate_combined(classpath, jvmdoc_targets, create_jvmdoc_command)
      else:
        self._generate_individual(classpath, jvmdoc_targets, create_jvmdoc_command)

    if catalog:
      for target in targets:
        gendir = self._gendir(target)
        jvmdocs = []
        for root, dirs, files in safe_walk(gendir):
          jvmdocs.extend(os.path.relpath(os.path.join(root, f), gendir) for f in files)
        self.context.products.get(self.jvmdoc().product_type).add(target, gendir, jvmdocs)

  def _generate_combined(self, classpath, targets, create_jvmdoc_command):
    gendir = os.path.join(self.workdir, 'combined')
    if targets:
      safe_mkdir(gendir, clean=True)
      command = create_jvmdoc_command(classpath, gendir, *targets)
      if command:
        self.context.log.debug("Running create_jvmdoc in {} with {}".format(gendir, " ".join(command)))
        result, gendir = create_jvmdoc(command, gendir)
        self._handle_create_jvmdoc_result(targets, result, command)
    if self.open:
      binary_util.ui_open(os.path.join(gendir, 'index.html'))

  def _generate_individual(self, classpath, targets, create_jvmdoc_command):
    jobs = {}
    for target in targets:
      gendir = self._gendir(target)
      command = create_jvmdoc_command(classpath, gendir, target)
      if command:
        jobs[gendir] = (target, command)

    if jobs:
      with contextlib.closing(
            multiprocessing.Pool(processes=min(len(jobs), multiprocessing.cpu_count()))) as pool:
        # map would be a preferable api here but fails after the 1st batch with an internal:
        # ...
        #  File "...src/python/pants/backend/core/tasks/jar_create.py", line 170, in javadocjar
        #      pool.map(createjar, jobs)
        #    File "...lib/python2.6/multiprocessing/pool.py", line 148, in map
        #      return self.map_async(func, iterable, chunksize).get()
        #    File "...lib/python2.6/multiprocessing/pool.py", line 422, in get
        #      raise self._value
        #  NameError: global name 'self' is not defined
        futures = []
        self.context.log.debug("Begin multiprocessing section; output may be misordered or garbled")
        try:
          for gendir, (target, command) in jobs.items():
            self.context.log.debug("Running create_jvmdoc in {} with {}"
                                   .format(gendir, " ".join(command)))
            futures.append(pool.apply_async(create_jvmdoc, args=(command, gendir)))

          for future in futures:
            result, gendir = future.get()
            target, command = jobs[gendir]
            self._handle_create_jvmdoc_result([target], result, command)
        finally:
          # In the event of an exception, we want to call terminate() because otherwise
          # we get errors on exit when multiprocessing tries to do it, because what
          # is dead may never die.
          pool.terminate()
          self.context.log.debug("End multiprocessing section")

  def _handle_create_jvmdoc_result(self, targets, result, command):
    if result != 0:
      targetlist = ", ".join(map(str, targets))
      message = 'Failed to process {} for {} [{}]: {}'.format(
                self.jvmdoc().tool_name, targetlist, result, command)
      if self.ignore_failure:
        self.context.log.warn(message)
      else:
        raise TaskError(message)

  def _gendir(self, target):
    return os.path.join(self.workdir, target.id)


def create_jvmdoc(command, gendir):
  try:
    safe_mkdir(gendir, clean=True)
    process = subprocess.Popen(command)
    result = process.wait()
    return result, gendir
  except OSError:
    return 1, gendir
