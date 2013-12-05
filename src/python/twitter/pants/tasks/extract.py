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

__author__ = 'Phil Hom'

import hashlib
import os

from collections import defaultdict

from twitter.common.contextutil import open_zip
from twitter.common.dirutil import safe_mkdir

from twitter.pants.base import Config, ParseContext
from twitter.pants.fs.archive import ZIP
from twitter.pants.targets import JarDependency, JavaThriftLibrary, SourceRoot
from twitter.pants.tasks import Task, TaskError


class Extract(Task):

  _PLACEHOLDER_BY_REQUEST = {}
  _PLACEHOLDERS_BY_JAR = defaultdict(list)
  _EXTRACT_BASE = None

  @classmethod
  def compiled_idl(cls, idl_dep, generated_deps=None, compiler=None, language=None, namespace_map=None):
    """Marks a jar as containing IDL files that should be fetched and processed locally.

    idl_dep:        A dependency resolvable to a single jar library.
    generated_deps: Dependencies for the code that will be generated from "idl_dep"
    compiler:       The thrift compiler to apply to the fetched thrift IDL files.
    language:       The language to generate code for - supported by some compilers
    namespace_map:  A mapping from IDL declared namespaces to custom namespaces - supported by some
                    compilers.
    """
    deps = [t for t in idl_dep.resolve() if t.is_concrete]
    if not len(deps) == 1:
      raise TaskError('Can only arrange for compiled idl for a single dependency at a time, '
                      'given:\n\t%s' % '\n\t'.join(map(str, deps)))
    jar = deps.pop()
    if not isinstance(jar, JarDependency):
      raise TaskError('Can only arrange for compiled idl from a jar dependency, given: %s' % jar)

    request = (jar, compiler, language)
    namespace_signature = None
    if namespace_map:
      sha = hashlib.sha1()
      for ns_from, ns_to in sorted(namespace_map.items()):
        sha.update(ns_from)
        sha.update(ns_to)
      namespace_signature = sha.hexdigest()
    request += (namespace_signature,)

    if request not in cls._PLACEHOLDER_BY_REQUEST:
      if not cls._EXTRACT_BASE:
        config = Config.load()
        cls._EXTRACT_BASE = config.get('idl-extract', 'workdir')
        safe_mkdir(cls._EXTRACT_BASE)
        SourceRoot.register(cls._EXTRACT_BASE, JavaThriftLibrary)

      with ParseContext.temp(cls._EXTRACT_BASE):
        # TODO(John Sirois): abstract ivy specific configurations notion away
        jar._configurations.append('idl')
        jar.with_artifact(configuration='idl', classifier='idl')
        target_name = '-'.join(filter(None, (jar.id, compiler, language, namespace_signature)))
        placeholder = JavaThriftLibrary(target_name,
                                        sources=None,
                                        dependencies=[jar] + (generated_deps or []),
                                        compiler=compiler,
                                        language=language,
                                        namespace_map=namespace_map)
        cls._PLACEHOLDER_BY_REQUEST[request] = placeholder
        cls._PLACEHOLDERS_BY_JAR[jar].append(placeholder)
    return cls._PLACEHOLDER_BY_REQUEST[request]

  def __init__(self, context):
    Task.__init__(self, context)

    self.placeholders = {}
    compiled_idl = set()
    for jar, placeholders in self._PLACEHOLDERS_BY_JAR.items():
      # Any representative placeholder for the jar will do for resolving, the compiler, language,
      # etc. do not come into play here; so we pick just one to minimize resolves.
      representative = placeholders[0]
      compiled_idl.add(representative)
      self.placeholders[representative] = placeholders

    def is_compiled_idl(target):
      return target in compiled_idl
    context.products.require('idl_dependencies', predicate=is_compiled_idl)

  def execute(self, targets):
    depmap = self.context.products.get('idl_dependencies')
    for representative, placeholders in self.placeholders.items():
      sources = set()
      mappings = depmap.get(representative)
      # When a BUILD file is eval'ed all its target constructors get run potentially registering
      # compiled_idl jars that are not actually used in the active target graph.  If the
      # compiled_idl is not active it will not have an 'idl_dependencies' mapping from the upstream
      # idl resolve - guard for this case.
      if mappings:
        for basedir, jars in mappings.items():
          for jar in jars:
            sources.update(self._extract(os.path.join(basedir, jar)))
      for placeholder in placeholders:
        placeholder.sources = sources

  def _extract(self, jarpath):
    self.context.log.debug('Extracting idl jar to: %s' % self._EXTRACT_BASE)
    ZIP.extract(jarpath, self._EXTRACT_BASE)
    with open_zip(jarpath) as jar:
      sources = filter(lambda path: path.endswith('.thrift'), jar.namelist())
      self.context.log.debug('Found thrift IDL sources: %s' % sources)
      return sources
