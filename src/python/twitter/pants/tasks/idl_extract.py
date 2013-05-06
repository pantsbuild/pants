# ==================================================================================================
# Copyright 2013 Twitter, Inc.
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

import os

from twitter.common.contextutil import open_zip
from twitter.common.dirutil import safe_open
from twitter.common.dirutil import safe_rmtree

from twitter.pants import get_buildroot
from twitter.pants.targets import IdlJvmThriftLibrary
from twitter.pants.tasks import Task, TaskError


class IdlExtract(Task):
  """Extracts idl thrift jars and points the sources to the extracted paths."""

  def _is_idl_jar_thrift_library(self, target):
    return isinstance(target, IdlJvmThriftLibrary)

  def __init__(self, context):
    Task.__init__(self, context)
    context.products.require('idl_dependencies', predicate=self._is_idl_jar_thrift_library)
    self._workdir = self.context.config.get('idl-extract', 'workdir')
    if self._workdir is None:
      self._workdir = os.path.join(self.get_workdir(), 'idl')

  def execute(self, targets):
    depmap = self.context.products.get('idl_dependencies')

    def process(target):
      sources = set()
      # TODO (tina): This should guard against items that haven't changed to prevent re-extraction
      extract_base = os.path.join(self._workdir, target.id)
      safe_rmtree(extract_base)
      target.target_base = os.path.relpath(extract_base, get_buildroot())
      for basedir, jars in depmap.get(target).items():
        if len(jars) != 1:
          raise TaskError(
            "%s must have exactly one jar dependency but found %s" % (target.name, jars))
        sources.update(self._extract(extract_base, os.path.join(basedir, jars[0])))
      target.sources = sources

    for target in targets:
      target.walk(process, predicate=lambda target: isinstance(target, IdlJvmThriftLibrary))

  def _extract(self, extract_base, jar_path):
    self.context.log.debug('Extracting idl jar %s to: %s' % (jar_path, extract_base))

    with open_zip(jar_path) as jar:
      sources = set()
      for path in jar.namelist():
        if path.endswith('.thrift'):
          contents = jar.read(path)
          with safe_open(os.path.join(extract_base, path), 'w') as out:
            out.write(contents)
          sources.add(path)

      self.context.log.debug('Found thrift IDL sources: %s' % sources)
      return sources
