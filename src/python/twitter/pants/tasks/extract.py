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

import hashlib
import os

from collections import defaultdict, namedtuple

from twitter.common.collections import maybe_list, OrderedSet
from twitter.common.contextutil import open_zip
from twitter.common.dirutil import safe_open, touch
from twitter.common.lang import Compatibility

from twitter.pants import get_buildroot, is_concrete, Config
from twitter.pants.base import manual, ParseContext
from twitter.pants.targets import (
    AnonymousDeps,
    JarLibrary,
    JavaThriftLibrary,
    Pants,
    SourceRoot,
    ThriftJar,
    ThriftLibrary)
from twitter.pants.tasks import Task, TaskError


class Extract(Task):

  _EXTRACT_BASES = {}

  @classmethod
  def _extract_base(cls, jar, config=None):
    if jar not in cls._EXTRACT_BASES:
      config = config or Config.load()
      extract_base = os.path.join(config.get('idl-extract', 'workdir'), jar.id)
      # TODO(John Sirois): creating an empty BUILD in the source-root is a hack to to work around
      # ephemeral targets being listed and then consumed by a new pants process as inputs - fix this
      # by introducing ephemeral targets as a 1st-level concept and revert to just ensuring the
      # extract_base dir exists.
      touch(os.path.join(extract_base, 'BUILD'))
      SourceRoot.register(extract_base, JavaThriftLibrary)
      cls._EXTRACT_BASES[jar] = extract_base
    return cls._EXTRACT_BASES[jar]

  class Request(namedtuple('Request', 'target_id compiler language rpc_style namespace_sig')):
    """Represents a request to materialize a pure thrift library into a target language."""

    @classmethod
    def create(cls, target_id, compiler, language, rpc_style, namespace_map=None):
      namespace_sig = None
      if namespace_map:
        sha = hashlib.sha1()
        for ns_from, ns_to in sorted(namespace_map.items()):
          sha.update(ns_from)
          sha.update(ns_to)
        namespace_sig = sha.hexdigest()
      return cls(target_id, compiler, language, rpc_style, namespace_sig)

  # map of Request -> JavaThriftLibrary
  _PLACEHOLDER_BY_REQUEST = {}

  @classmethod
  def _register_once(cls, name, id_, compiler, language, rpc_style, namespace_map, basedir, create):
    """Create and register a ``JavaThriftLibrary`` representing a ``ThriftLibrary``
    and its thrift codegen options.

    :returns: The :class:`twitter.pants.targets.java_thrift_library.JavaThriftLibrary`
      representing the requested thrift codegen.
    """
    request = cls.Request.create(id_, compiler, language, rpc_style, namespace_map)
    if request not in cls._PLACEHOLDER_BY_REQUEST:
      with ParseContext.temp(basedir):
        unique_name = '-'.join(val for val in request._replace(target_id=name) if val is not None)
        placeholder = create(unique_name)
        assert(isinstance(placeholder, JavaThriftLibrary))
      cls._PLACEHOLDER_BY_REQUEST[request] = placeholder
    return cls._PLACEHOLDER_BY_REQUEST[request]

  _PLACEHOLDERS_BY_JAR = defaultdict(list)
  _REGISTERED_JARS = set()

  @classmethod
  def _register_jar(cls, jar, compiler=None, language=None, rpc_style=None, generated_deps=None,
                    namespace_map=None):

    def create(name):
      synthetic = JavaThriftLibrary(name,
                                    sources=None,
                                    dependencies=[jar] + (generated_deps or []),
                                    compiler=compiler,
                                    language=language,
                                    rpc_style=rpc_style,
                                    namespace_map=namespace_map)
      synthetic.derived_from = jar
      cls._PLACEHOLDERS_BY_JAR[jar].append(synthetic)
      cls._REGISTERED_JARS.add((jar.org, jar.name))
      return synthetic
    return cls._register_once(jar.id, jar.id, compiler, language, rpc_style, namespace_map,
                              cls._extract_base(jar), create)

  @classmethod
  def is_registered_jar(cls, org, name):
    """Check if the jar is registered.

    :param string org: Maven groupId of the jar.
    :param string name: Maven artifactId of the jar.
    :returns: True if the jar is registered.
    :rtype: bool
    """
    assert(isinstance(org, Compatibility.string))
    assert(isinstance(name, Compatibility.string))
    return (org, name) in cls._REGISTERED_JARS

  @classmethod
  def _register_library(cls, library, compiler=None, language=None, rpc_style=None,
                        generated_deps=None, namespace_map=None):
    """Register a JavaThriftLibrary corresponding to the given ThriftLibrary.

    :param library: The :class:`twitter.pants.targets.thrift_library.ThriftLibrary`
      to register.
    :param string compiler: Name of the thrift compiler to generate sources with.
    :param string language: Language to generate code for
      (only supported by some compilers).
    :param string rpc_style: Style of RPC service stubs to generate
      (only supported by some compilers).
    :param generated_deps: Dependencies for the code that will be generated
      from the ``idl_deps``.
    :param namespace_map: A mapping from IDL declared namespaces to custom
      namespaces (only supported by some compilers).
    :returns: A :class:`twitter.pants.targets.java_thrift_library.JavaThriftLibrary`
      target that owns the generated code.
    """

    assert(isinstance(library, ThriftLibrary))
    basedir = library.address.buildfile.parent_path

    def create(name):
      # TODO(John Sirois): make the internals of targets and source path ownership easier to handle
      # with utilities or mixins that consolidate this handling centrally.

      # Sources should be relative to the BUILD file, so we need to do some math since paths go in
      # relative and come out (library.sources) qualified.
      #
      # In particular, given:
      #  source_root: src/thrift
      #  BUILD: com/twitter/base/BUILD
      #  thrift BUILD relative path: v1/api.thrift
      #
      # Such that we have the source file: src/thrift/com/twitter/base/v1/api.thrift
      # And the target: src/thrift/com/twitter/base:api-v1
      #
      # The BUILD target has input sources:
      #  lib = thrift_library(name='api-v1', sources=['v1/api.thrift'])
      #
      # Which is resolved such that:
      #   assert lib.sources == ['com/twitter/base/v1/api.thrift']
      #
      # IE: the target sources are relative to the target_base
      sources = [os.path.relpath(os.path.join(get_buildroot(), library.target_base, path), basedir)
                 for path in library.sources]

      synthetic = JavaThriftLibrary('__compiled_idl_%s' % (name),
                                    sources=sources,
                                    dependencies=generated_deps,
                                    compiler=compiler,
                                    language=language,
                                    rpc_style=rpc_style,
                                    namespace_map=namespace_map)
      synthetic.derived_from = library
      return synthetic
    return cls._register_once(library.name, library.id, compiler, language, rpc_style,
                              namespace_map, basedir, create)

  @classmethod
  @manual.builddict(tags=["anylang", "thrift"])
  def compiled_idl(cls, idl_deps, name=None, compiler=None, language=None, rpc_style=None,
                   generated_deps=None, namespace_map=None):
    """Configure thrift IDL code generation.

    This is where "things that represent thrift IDL files" converge with
    a thrift compiler (and the compiler options) to generate code. For thrift
    jar IDL dependencies fetching and extraction are scheduled as well.

    Two usages are supported:

    * Creating an addressable target that may be depended on by other targets
      (this requires specifying the ``name`` parameter). This is the recommended
      usage so many targets may depend on the same codegen. A typical usage
      of ``namespace_map`` is for JVM languages to overload package names with
      the target language to avoid classpath naming conflicts in mixed
      language classpaths.
    * Creating an inline anonymous target. This is typically used in
      conjunction with ``namespace_map`` when generating code into a custom
      namespace.

    Let's examine an example addressable target, which is the recommended
    usage. Typically the thrift IDL owner would provide such a target for
    others to depend on.

    ::

      compiled_idl(name='mybird-scala'
        idl_deps=[pants(':idl')],
        compiler='scrooge',
        language='scala',
        namespace_map={
          'com.twitter.mybird.thriftjava': 'com.twitter.mybird.thriftscala',
        }
      )

      thrift_library(name='idl',
        sources=globs('*.thrift')
      )

    Now let's examine an example anonymous target usage. Notice how this
    project chooses to generate code into a private namespace. It also chooses
    to map thriftjava to thriftscala to avoid classpath issues.

    ::

      scala_library(name='mybird',
        dependencies=[
          compiled_idl(
            idl_deps=[pants('src/thrift/com/twitter/otherbird')],
            compiler='scrooge',
            language='scala',
            namespace_map={
              'com.twitter.otherbird.thriftjava': 'com.twitter.mybird.otherbird.thriftscala',
            },
          ),
        ],
        sources=globs('*.scala'),
      )

    :param idl_deps: One or more dependencies resolvable to a set of
      :class:`twitter.pants.targets.thrift_library.ThriftJar` or
      :class:`twitter.pants.targets.thrift_library.ThriftLibrary` targets.
    :param string name: Name of the returned target so it can be
      referenced. Anonymous (un-addressable) by default.
    :param string compiler: Name of the thrift compiler to generate sources with.
    :param string language: Language to generate code for
      (only supported by some compilers).
    :param string rpc_style: Style of RPC service stubs to generate
      (only supported by some compilers).
    :param generated_deps: Dependencies for the code that will be generated
      from the ``idl_deps``.
    :param namespace_map: A mapping from IDL declared namespaces to custom
      namespaces (only supported by some compilers).
    :returns: A :class:`twitter.pants.targets.jar_library.JarLibrary` that
      depends on
      :class:`twitter.pants.targets.java_thrift_library.JavaThriftLibrary`
      targets that own the generated code.
    """
    def stitch_dependencies(synthetic_jarlib):
      thrift_jars = OrderedSet()
      thrift_libraries = OrderedSet()
      invalid = OrderedSet()

      def is_thrift_jar(dep):
        return isinstance(dep, ThriftJar)

      def accumulate(dep):
        if is_thrift_jar(dep):
          thrift_jars.add(dep)
        elif isinstance(dep, ThriftLibrary):
          thrift_libraries.add(dep)
          thrift_jars.update(filter(is_thrift_jar, dep.dependencies))
        else:
          invalid.add(dep)

      for idl_dep in maybe_list(idl_deps,
                                expected_type=(JarLibrary, Pants, ThriftJar, ThriftLibrary),
                                raise_type=TaskError):
        idl_dep.walk(accumulate, predicate=is_concrete)

      if invalid:
        raise TaskError('Can only arrange for compiled idl from thrift jars and thrift libraries, '
                        'found the following non-compliant dependencies:\n\t%s'
                        % '\n\t'.join(map(str, invalid)))

      synthetic_by_idl = {}
      for thrift_jar in thrift_jars:
        synthetic_by_idl[thrift_jar] = cls._register_jar(thrift_jar, compiler, language, rpc_style,
                                                         generated_deps, namespace_map)

      for thrift_library in thrift_libraries:
        synthetic_by_idl[thrift_library] = cls._register_library(thrift_library, compiler, language,
                                                                 rpc_style, generated_deps,
                                                                 namespace_map)

      # Stitch dependencies between the synthetic targets that mirror the IDL inter-dependencies.
      for thrift_library in thrift_libraries:
        synthetic_deps = OrderedSet()
        for dependency in thrift_library.dependencies:
          for dep in dependency.resolve():
            if is_concrete(dep):
              synthetic_deps.add(synthetic_by_idl[dep])
        synthetic_by_idl[thrift_library].update_dependencies(synthetic_deps)
      synthetic_jarlib.dependencies.update(synthetic_by_idl.values())

    synthetic_lib = JarLibrary(name=name, dependencies=()) if name else AnonymousDeps()
    ParseContext.locate().on_context_exit(stitch_dependencies, synthetic_lib)
    return synthetic_lib

  def __init__(self, context):
    Task.__init__(self, context)

    self._placeholders = {}
    compiled_idl = set()
    for thrift_jar, placeholders in self._PLACEHOLDERS_BY_JAR.items():
      # When a BUILD file is eval'ed all its target constructors get run potentially registering
      # compiled_idl jars that are not actually used in the active target graph - guard for this
      # case and only act on those placeholders active in the context.
      active_placeholders = self.context.targets(predicate=placeholders.__contains__)
      if active_placeholders:
        # Any representative active placeholder for the jar will do for resolving, the compiler,
        # language, etc. do not come into play here; so we pick just one to minimize resolves.
        representative = active_placeholders[0]
        self.context.log.debug('Fetching thrift jar %s via representative %s'
                               % (thrift_jar, representative))
        compiled_idl.add(representative)

        self._placeholders[(thrift_jar, representative)] = active_placeholders

    def is_compiled_idl(target):
      return target in compiled_idl

    context.products.require('idl_dependencies', predicate=is_compiled_idl)

  def execute(self, _):
    depmap = self.context.products.get('idl_dependencies')
    for (thrift_jar, representative), placeholders in self._placeholders.items():
      sources = set()
      extract_base = self._extract_base(thrift_jar)
      for basedir, jars in depmap.get(representative).items():
        for jar in jars:
          sources.update(self._extract(extract_base, os.path.join(basedir, jar)))

      for placeholder in placeholders:
        placeholder.sources = sources

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
