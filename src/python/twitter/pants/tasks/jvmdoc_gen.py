# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import collections
import contextlib
import multiprocessing
import os
import subprocess

from twitter.common.dirutil import safe_mkdir

from pants import binary_util
from pants.tasks import Task, TaskError


Jvmdoc = collections.namedtuple('Jvmdoc', ['tool_name', 'product_type'])

ParserConfig = collections.namedtuple(
                'JvmdocGenParserConfig',
                ['outdir_opt', 'include_codegen_opt', 'transitive_opt', 'open_opt', 'combined_opt',
                 'ignore_failure_opt'])


class JvmdocGen(Task):
  @classmethod
  def setup_parser_config(cls):
    opts = ['%s_%s' % (cls.__name__, opt) for opt in ParserConfig._fields]
    return ParserConfig(*opts)

  @classmethod
  def generate_setup_parser(cls, option_group, args, mkflag, jvmdoc):
    parser_config = cls.setup_parser_config()
    option_group.add_option(
      mkflag('outdir'),
      dest=parser_config.outdir_opt,
      help='Emit %s in this directory.' % jvmdoc.tool_name)

    option_group.add_option(
      mkflag('include-codegen'),
      mkflag('include-codegen', negate=True),
      dest=parser_config.include_codegen_opt,
      default=None,
      action='callback',
      callback=mkflag.set_bool,
      help='[%%default] Create %s for generated code.' % jvmdoc.tool_name)

    option_group.add_option(
      mkflag('transitive'),
      mkflag('transitive', negate=True),
      dest=parser_config.transitive_opt,
      default=True,
      action='callback',
      callback=mkflag.set_bool,
      help='[%%default] Create %s for the transitive closure of internal '
           'targets reachable from the roots specified on the command line.'
           % jvmdoc.tool_name)

    combined_flag = mkflag('combined')
    option_group.add_option(
      combined_flag,
      mkflag('combined', negate=True),
      dest=parser_config.combined_opt,
      default=False,
      action='callback',
      callback=mkflag.set_bool,
      help='[%%default] Generate %s for all targets combined instead of '
           'each target individually.'
           % jvmdoc.tool_name)

    option_group.add_option(
      mkflag('open'),
      mkflag('open', negate=True),
      dest=parser_config.open_opt,
      default=False,
      action='callback',
      callback=mkflag.set_bool,
      help='[%%default] Attempt to open the generated %s in a browser '
           '(implies %s).' % (jvmdoc.tool_name, combined_flag))

    option_group.add_option(
      mkflag('ignore-failure'),
      mkflag('ignore-failure', negate=True),
      dest=parser_config.ignore_failure_opt,
      default=False,
      action='callback',
      callback=mkflag.set_bool,
      help='Specifies that %s errors should not cause build errors'
           % jvmdoc.tool_name)

  def __init__(self, context, jvmdoc, output_dir, confs, active):
    def getattr_options(option):
      return getattr(context.options, option)

    super(JvmdocGen, self).__init__(context)

    self._jvmdoc = jvmdoc
    jvmdoc_tool_name = self._jvmdoc.tool_name

    config_section = '%s-gen' % jvmdoc_tool_name
    parser_config = self.setup_parser_config()

    pants_workdir = context.config.getdefault('pants_workdir')
    self._output_dir = (
      output_dir
      or getattr_options(parser_config.outdir_opt)
      or context.config.get(config_section,
                            'workdir',
                            default=os.path.join(pants_workdir, jvmdoc_tool_name))
    )

    flagged_codegen = getattr_options(parser_config.include_codegen_opt)
    self._include_codegen = (flagged_codegen if flagged_codegen is not None
                             else context.config.getbool(config_section, 'include_codegen',
                                                         default=False))

    self.transitive = getattr_options(parser_config.transitive_opt)
    self.confs = confs or context.config.getlist(config_section, 'confs', default=['default'])
    self.active = active
    self.open = getattr_options(parser_config.open_opt)
    self.combined = self.open or getattr_options(parser_config.combined_opt)
    self.ignore_failure = getattr_options(parser_config.ignore_failure_opt)

  def invalidate_for(self):
    return (self.combined, self.transitive, self._output_dir, self.confs, self._include_codegen)

  def generate_execute(self, targets, language_predicate, create_jvmdoc_command):
    """
    Generate an execute method given a language predicate and command to create documentation

    language_predicate: a function that accepts a target and returns True if the target is of that
                        language
    create_jvmdoc_command: (classpath, directory, *targets) -> command (string) that will generate
                           documentation documentation for targets
    """
    catalog = self.context.products.isrequired(self._jvmdoc.product_type)
    if catalog and self.combined:
      raise TaskError(
          'Cannot provide %s target mappings for combined output' % self._jvmdoc.product_type)
    elif catalog or self.active:
      def docable(target):
        return language_predicate(target) and (self._include_codegen or not is_codegen(target))

      with self.invalidated(filter(docable, targets)) as invalidation_check:
        safe_mkdir(self._output_dir)
        with self.context.state('classpath', []) as cp:
          classpath = [jar for conf, jar in cp if conf in self.confs]

          def find_jvmdoc_targets():
            invalid_targets = set()
            for vt in invalidation_check.invalid_vts:
              invalid_targets.update(vt.targets)

            if self.transitive:
              return invalid_targets
            else:
              return set(invalid_targets).intersection(set(self.context.target_roots))

          jvmdoc_targets = list(filter(docable, find_jvmdoc_targets()))
          if self.combined:
            self._generate_combined(classpath, jvmdoc_targets, create_jvmdoc_command)
          else:
            self._generate_individual(classpath, jvmdoc_targets, create_jvmdoc_command)

      if catalog:
        for target in targets:
          gendir = self._gendir(target)
          jvmdocs = []
          for root, dirs, files in os.walk(gendir):
            jvmdocs.extend(os.path.relpath(os.path.join(root, f), gendir) for f in files)
          self.context.products.get(self._jvmdoc.product_type).add(target, gendir, jvmdocs)

  def _generate_combined(self, classpath, targets, create_jvmdoc_command):
    gendir = os.path.join(self._output_dir, 'combined')
    if targets:
      safe_mkdir(gendir, clean=True)
      command = create_jvmdoc_command(classpath, gendir, *targets)
      if command:
        create_jvmdoc(command, gendir)
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
        #  File "...src/python/pants/tasks/jar_create.py", line 170, in javadocjar
        #      pool.map(createjar, jobs)
        #    File "...lib/python2.6/multiprocessing/pool.py", line 148, in map
        #      return self.map_async(func, iterable, chunksize).get()
        #    File "...lib/python2.6/multiprocessing/pool.py", line 422, in get
        #      raise self._value
        #  NameError: global name 'self' is not defined
        futures = []
        for gendir, (target, command) in jobs.items():
          futures.append(pool.apply_async(create_jvmdoc, args=(command, gendir)))

        for future in futures:
          result, gendir = future.get()
          target, command = jobs[gendir]
          if result != 0:
            message = 'Failed to process %s for %s [%d]: %s' % (
                      self._jvmdoc.tool_name, target, result, command)
            if self.ignore_failure:
              self.context.log.warn(message)
            else:
              raise TaskError(message)

  def _gendir(self, target):
    return os.path.join(self._output_dir, target.id)


def create_jvmdoc(command, gendir):
  safe_mkdir(gendir, clean=True)
  process = subprocess.Popen(command)
  result = process.wait()
  return result, gendir
