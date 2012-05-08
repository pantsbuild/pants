# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

__author__ = 'John Sirois'

import os
import subprocess
import multiprocessing

from twitter.common.dirutil import safe_mkdir
from twitter.pants import is_jvm, JavaLibrary, JavaTests
from twitter.pants.tasks import binary_utils, Task, TaskError

def is_java(target):
  return isinstance(target, JavaLibrary) or isinstance(target, JavaTests)


class JavadocGen(Task):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("outdir"), dest="javadoc_gen_outdir",
                            help="Emit javadoc in this directory.")

    option_group.add_option(mkflag("transitive"), mkflag("transitive", negate=True),
                            dest="javadoc_gen_transitive", default=True,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Create javadoc for the transitive closure of internal "
                                 "targets reachable from the roots specified on the command line.")

    combined_flag = mkflag("combined")
    option_group.add_option(combined_flag, mkflag("combined", negate=True),
                            dest="javadoc_gen_combined", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Generate javadoc for all targets combined instead of "
                                 "each target individually.")

    option_group.add_option(mkflag("open"), mkflag("open", negate=True),
                            dest="javadoc_gen_open", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%%default] Attempt to open the generated javadoc in a browser "
                                 "(implies %s)." % combined_flag)

  def __init__(self, context, output_dir=None, confs=None):
    Task.__init__(self, context)

    self._output_dir = (
      output_dir
      or context.options.javadoc_gen_outdir
      or context.config.get('javadoc-gen', 'workdir')
    )
    self.transitive = context.options.javadoc_gen_transitive
    self.confs = confs or context.config.getlist('javadoc-gen', 'confs')
    self.open = context.options.javadoc_gen_open
    self.combined = self.open or context.options.javadoc_gen_combined

  def invalidate_for(self):
    return self.combined

  def execute(self, targets):
    catalog = self.context.products.isrequired('javadoc')
    if catalog and self.combined:
      raise TaskError('Cannot provide javadoc target mappings for combined output')

    with self.changed(filter(is_java, targets)) as changed_targets:
      safe_mkdir(self._output_dir)
      with self.context.state('classpath', []) as cp:
        classpath = [jar for conf, jar in cp if conf in self.confs]

        def find_javadoc_targets():
          if self.transitive:
            return changed_targets
          else:
            return set(changed_targets).intersection(set(self.context.target_roots))

        javadoc_targets = list(filter(is_java, find_javadoc_targets()))
        if self.combined:
          self.generate_combined(classpath, javadoc_targets)
        else:
          self.generate_individual(classpath, javadoc_targets)

    if catalog:
      for target in targets:
        gendir = self._gendir(target)
        javadocs = []
        for root, dirs, files in os.walk(gendir):
          javadocs.extend(os.path.relpath(os.path.join(root, f), gendir) for f in files)
        self.context.products.get('javadoc').add(target, gendir, javadocs)

  def generate_combined(self, classpath, targets):
    gendir = os.path.join(self._output_dir, 'combined')
    if targets:
      safe_mkdir(gendir, clean=True)
      command = create_javadoc_command(classpath, gendir, *targets)
      if command:
        create_javadoc(command, gendir)
    if self.open:
      binary_utils.open(os.path.join(gendir, 'index.html'))

  def generate_individual(self, classpath, targets):
    jobs = {}
    for target in targets:
      gendir = self._gendir(target)
      command = create_javadoc_command(classpath, gendir, target)
      if command:
        jobs[gendir] = (target, command)

    pool = multiprocessing.Pool(processes=min(len(jobs), multiprocessing.cpu_count()))
    try:
      # map would be a preferable api here but fails after the 1st batch with an internal:
      # ...
      #  File "...src/python/twitter/pants/tasks/jar_create.py", line 170, in javadocjar
      #      pool.map(createjar, jobs)
      #    File "...lib/python2.6/multiprocessing/pool.py", line 148, in map
      #      return self.map_async(func, iterable, chunksize).get()
      #    File "...lib/python2.6/multiprocessing/pool.py", line 422, in get
      #      raise self._value
      #  NameError: global name 'self' is not defined
      futures = []
      for gendir, (target, command) in jobs.items():
        futures.append(pool.apply_async(create_javadoc, args=(command, gendir)))

      for future in futures:
        result, gendir = future.get()
        target, command = jobs[gendir]
        if result != 0:
          raise TaskError('Failed to process javadoc for %s [%d]: %s' % (target, result, command))

    finally:
      pool.close()

  def _gendir(self, target):
    return os.path.join(self._output_dir, target.id)

def create_javadoc_command(classpath, gendir, *targets):
  sources = []
  for target in targets:
    sources.extend(os.path.join(target.target_base, source) for source in target.sources)

  if not sources:
    return None

  # TODO(John Sirois): try com.sun.tools.javadoc.Main via ng
  command = [
    'javadoc',
    '-quiet',
    '-encoding', 'UTF-8',
    '-notimestamp',
    '-use',
    '-classpath', ':'.join(classpath),
    '-d', gendir,
  ]

  # Always provide external linking for java API
  offlinelinks = set(['http://download.oracle.com/javase/6/docs/api/'])
  def link(target):
    for jar in target.jar_dependencies:
      if jar.apidocs:
        offlinelinks.add(jar.apidocs)
  for target in targets:
    target.walk(link, is_jvm)

  for link in offlinelinks:
    command.extend(['-linkoffline', link, link])

  command.extend(sources)
  return command


def create_javadoc(command, gendir):
  safe_mkdir(gendir, clean=True)
  process = subprocess.Popen(command)
  result = process.wait()
  return result, gendir
