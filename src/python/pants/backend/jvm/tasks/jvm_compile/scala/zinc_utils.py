# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from itertools import chain

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.hash_utils import hash_file
from pants.base.workunit import WorkUnit
from pants.util.dirutil import relativize_paths


# TODO: Fold this into ScalaCompile. Or at least the non-static parts.
# Right now it has to access so much state from that task that we have to pass it a reference back
# to the task.  This separation was primarily motivated  by the fact that we used to run Zinc for
# other reasons (such as split/merge/rebase of analysis files). But now ScalaCompile is the
# only client.
class ZincUtils(object):
  """Convenient wrapper around zinc invocations.

  Instances are immutable, and all methods are reentrant (assuming that the java_runner is).
  """

  _ZINC_MAIN = 'com.typesafe.zinc.Main'

  def __init__(self, context, nailgun_task, jvm_options, color=True, log_level='info'):
    self.context = context
    self._nailgun_task = nailgun_task  # We run zinc on this task's behalf.
    self._jvm_options = jvm_options
    self._color = color
    self._log_level = log_level

  @property
  def _zinc_classpath(self):
    return self._nailgun_task.zinc_classpath()

  @property
  def _compiler_classpath(self):
    return self._nailgun_task.compiler_classpath()

  def _zinc_jar_args(self):
    zinc_jars = self.identify_zinc_jars(self._zinc_classpath)
    # The zinc jar names are also the flag names.
    return (list(chain.from_iterable([['-{}'.format(name), jarpath]
                                     for (name, jarpath) in sorted(zinc_jars.items())])) +
            ['-scala-path', ':'.join(self._compiler_classpath)])

  @staticmethod
  def relativize_classpath(classpath):
    return relativize_paths(classpath, get_buildroot())

  def compile(self, extra_args, classpath, sources, output_dir,
              analysis_file, upstream_analysis_files):

    # We add compiler_classpath to ensure the scala-library jar is on the classpath.
    # TODO: This also adds the compiler jar to the classpath, which compiled code shouldn't
    # usually need. Be more selective?
    relativized_classpath = self.relativize_classpath(self._compiler_classpath + classpath)

    args = []

    args.extend([
      '-log-level', self._log_level,
      '-analysis-cache', analysis_file,
      '-classpath', ':'.join(relativized_classpath),
      '-d', output_dir
    ])
    if not self._color:
      args.append('-no-color')
    if not self._nailgun_task.name_hashing():
      args.append('-no-name-hashing')

    args.extend(self._zinc_jar_args())
    args += self._nailgun_task.plugin_args()
    if upstream_analysis_files:
      args.extend(
        ['-analysis-map', ','.join(['{}:{}'.format(*kv) for kv in upstream_analysis_files.items()])])

    args += extra_args

    args.extend(sources)

    self.log_zinc_file(analysis_file)
    if self._nailgun_task.runjava(classpath=self._zinc_classpath,
                                  main=self._ZINC_MAIN,
                                  jvm_options=self._jvm_options,
                                  args=args,
                                  workunit_name='zinc',
                                  workunit_labels=[WorkUnit.COMPILER]):
      raise TaskError('Zinc compile failed.')

  # These are the names of the various jars zinc needs. They are, conveniently and
  # non-coincidentally, the names of the flags used to pass the jar locations to zinc.
  ZINC_JAR_NAMES = ['compiler-interface', 'sbt-interface']

  @classmethod
  def identify_zinc_jars(cls, zinc_classpath):
    """Find the named jars in the zinc classpath.

    TODO: Make these mappings explicit instead of deriving them by jar name heuristics.
    """
    jars_by_name = {}
    jars_and_filenames = [(x, os.path.basename(x)) for x in zinc_classpath]

    for name in cls.ZINC_JAR_NAMES:
      jar_for_name = None
      for jar, filename in jars_and_filenames:
        if filename.startswith(name):
          jar_for_name = jar
          break
      if jar_for_name is None:
        raise TaskError('Couldn\'t find jar named {}'.format(name))
      else:
        jars_by_name[name] = jar_for_name
    return jars_by_name

  def log_zinc_file(self, analysis_file):
    self.context.log.debug('Calling zinc on: {} ({})'
                           .format(analysis_file,
                                   hash_file(analysis_file).upper()
                                   if os.path.exists(analysis_file)
                                   else 'nonexistent'))
