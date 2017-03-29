# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import re
from abc import abstractmethod
from os import sep as os_sep
from os.path import join as os_path_join

from pants.base.exceptions import TaskError
from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.base.project_tree import Dir
from pants.build_graph.address import Address
from pants.engine.addressable import BuildFileAddresses, SubclassesOf, addressable_list
from pants.engine.build_files import create_graph_rules
from pants.engine.fs import FilesContent, PathGlobs, Snapshot, create_fs_rules
from pants.engine.mapper import AddressFamily, AddressMapper
from pants.engine.parser import SymbolTable
from pants.engine.rules import SingletonRule, TaskRule, rule
from pants.engine.scheduler import LocalScheduler
from pants.engine.selectors import Select, SelectDependencies, SelectProjection, SelectVariant
from pants.engine.struct import HasProducts, Struct, StructWithDeps, Variants
from pants.util.meta import AbstractClass
from pants.util.objects import datatype
from pants_test.engine.examples.parsers import JsonParser
from pants_test.engine.examples.sources import Sources


def printing_func(func):
  @functools.wraps(func)
  def wrapper(*inputs):
    product = func(*inputs)
    return_val = product if product else '<<<Fake-{}-Product>>>'.format(func.__name__)
    print('{} executed for {}, returned: {}'.format(func.__name__, inputs, return_val))
    return return_val
  return wrapper


class Target(Struct, HasProducts):
  """A placeholder for the most-numerous Struct subclass.

  This particular implementation holds a collection of other Structs in a `configurations` field.
  """

  def __init__(self, name=None, configurations=None, **kwargs):
    """
    :param string name: The name of this target which forms its address in its namespace.
    :param list configurations: The configurations that apply to this target in various contexts.
    """
    super(Target, self).__init__(name=name, **kwargs)

    self.configurations = configurations

  @property
  def products(self):
    return self.configurations

  @addressable_list(SubclassesOf(Struct))
  def configurations(self):
    """The configurations that apply to this target in various contexts.

    :rtype list of :class:`pants.engine.configuration.Struct`
    """


class JavaSources(Sources, StructWithDeps):
  extensions = ('.java',)


class ScalaSources(Sources, StructWithDeps):
  extensions = ('.scala',)


class PythonSources(Sources, StructWithDeps):
  extensions = ('.py',)


class ThriftSources(Sources, StructWithDeps):
  extensions = ('.thrift',)


class ResourceSources(Sources):
  extensions = tuple()


class ScalaInferredDepsSources(Sources):
  """A Sources subclass which can be converted to ScalaSources via dep inference."""
  extensions = ('.scala',)


class ImportedJVMPackages(datatype('ImportedJVMPackages', ['dependencies'])):
  """Holds a list of 'JVMPackageName' dependencies."""
  pass


class JVMPackageName(datatype('JVMPackageName', ['name'])):
  """A typedef to represent a fully qualified JVM package name."""
  pass


class SourceRoots(datatype('SourceRoots', ['srcroots'])):
  """Placeholder for the SourceRoot subsystem."""


@rule(Address,
      [Select(JVMPackageName),
       SelectDependencies(AddressFamily, Snapshot, field='dir_stats', field_types=(Dir,))])
@printing_func
def select_package_address(jvm_package_name, address_families):
  """Return the Address from the given AddressFamilies which provides the given package."""
  addresses = [address for address_family in address_families
                       for address in address_family.addressables.keys()]
  if len(addresses) == 0:
    raise ValueError('No targets existed in {} to provide {}'.format(
      address_families, jvm_package_name))
  elif len(addresses) > 1:
    raise ValueError('Multiple targets might be able to provide {}:\n  {}'.format(
      jvm_package_name, '\n  '.join(str(a) for a in addresses)))
  return addresses[0].to_address()


@rule(PathGlobs, [Select(JVMPackageName), Select(SourceRoots)])
@printing_func
def calculate_package_search_path(jvm_package_name, source_roots):
  """Return PathGlobs to match directories where the given JVMPackageName might exist."""
  rel_package_dir = jvm_package_name.name.replace('.', os_sep)
  specs = [os_path_join(srcroot, rel_package_dir) for srcroot in source_roots.srcroots]
  return PathGlobs.create('', include=specs)


@rule(ImportedJVMPackages,
      [SelectProjection(FilesContent, PathGlobs, 'path_globs', ScalaInferredDepsSources)])
@printing_func
def extract_scala_imports(source_files_content):
  """A toy example of dependency inference. Would usually be a compiler plugin."""
  packages = set()
  import_re = re.compile(r'^import ([^;]*);?$')
  for filecontent in source_files_content.dependencies:
    for line in filecontent.content.splitlines():
      match = import_re.search(line)
      if match:
        packages.add(match.group(1).rsplit('.', 1)[0])
  return ImportedJVMPackages([JVMPackageName(p) for p in packages])


@rule(ScalaSources,
      [Select(ScalaInferredDepsSources),
       SelectDependencies(Address, ImportedJVMPackages, field_types=(JVMPackageName,))])
@printing_func
def reify_scala_sources(sources, dependency_addresses):
  """Given a ScalaInferredDepsSources object and its inferred dependencies, create ScalaSources."""
  kwargs = sources._asdict()
  kwargs['dependencies'] = list(set(dependency_addresses))
  return ScalaSources(**kwargs)


class Requirement(Struct):
  """A setuptools requirement."""

  def __init__(self, req, repo=None, **kwargs):
    """
    :param string req: A setuptools compatible requirement specifier; eg: `pantsbuild.pants>0.0.42`.
    :param string repo: An optional custom find-links repo URL.
    """
    super(Requirement, self).__init__(req=req, repo=repo, **kwargs)


class Classpath(Struct):
  """Placeholder product."""

  def __init__(self, creator, **kwargs):
    super(Classpath, self).__init__(creator=creator, **kwargs)


class ManagedResolve(Struct):
  """A frozen ivy resolve that when combined with a ManagedJar can produce a Jar."""

  def __init__(self, revs, **kwargs):
    """
    :param dict revs: A dict of artifact org#name to version.
    """
    super(ManagedResolve, self).__init__(revs=revs, **kwargs)

  def __repr__(self):
    return "ManagedResolve({})".format(self.revs)


class Jar(Struct):
  """A java jar."""

  def __init__(self, org=None, name=None, rev=None, **kwargs):
    """
    :param string org: The Maven ``groupId`` of this dependency.
    :param string name: The Maven ``artifactId`` of this dependency; also serves as the name portion
                        of the address of this jar if defined at the top level of a BUILD file.
    :param string rev: The Maven ``version`` of this dependency.
    """
    super(Jar, self).__init__(org=org, name=name, rev=rev, **kwargs)


class ManagedJar(Struct):
  """A java jar template, which can be merged with a ManagedResolve to determine a concrete version."""

  def __init__(self, org, name, **kwargs):
    """
    :param string org: The Maven ``groupId`` of this dependency.
    :param string name: The Maven ``artifactId`` of this dependency; also serves as the name portion
                        of the address of this jar if defined at the top level of a BUILD file.
    """
    super(ManagedJar, self).__init__(org=org, name=name, **kwargs)


@rule(Jar, [Select(ManagedJar), SelectVariant(ManagedResolve, 'resolve')])
@printing_func
def select_rev(managed_jar, managed_resolve):
  (org, name) = (managed_jar.org, managed_jar.name)
  rev = managed_resolve.revs.get('{}#{}'.format(org, name), None)
  if not rev:
    raise TaskError('{} does not have a managed version in {}.'.format(managed_jar, managed_resolve))
  return Jar(org=managed_jar.org, name=managed_jar.name, rev=rev)


@rule(Classpath, [Select(Jar)])
@printing_func
def ivy_resolve(jars):
  return Classpath(creator='ivy_resolve')


@rule(Classpath, [Select(ResourceSources)])
@printing_func
def isolate_resources(resources):
  """Copies resources into a private directory, and provides them as a Classpath entry."""
  return Classpath(creator='isolate_resources')


class ThriftConfiguration(StructWithDeps):
  pass


class ApacheThriftConfiguration(ThriftConfiguration):
  def __init__(self, rev=None, strict=True, **kwargs):
    """
    :param string rev: The version of the apache thrift compiler to use.
    :param bool strict: `False` to turn strict compiler warnings off (not recommended).
    """
    super(ApacheThriftConfiguration, self).__init__(rev=rev, strict=strict, **kwargs)


class ApacheThriftJavaConfiguration(ApacheThriftConfiguration):
  pass


class ApacheThriftPythonConfiguration(ApacheThriftConfiguration):
  pass


class ApacheThriftError(TaskError):
  pass


@rule(JavaSources, [Select(ThriftSources), SelectVariant(ApacheThriftJavaConfiguration, 'thrift')])
def gen_apache_java_thrift(sources, config):
  return gen_apache_thrift(sources, config)


@rule(PythonSources, [Select(ThriftSources), SelectVariant(ApacheThriftPythonConfiguration, 'thrift')])
def gen_apache_python_thrift(sources, config):
  return gen_apache_thrift(sources, config)


@printing_func
def gen_apache_thrift(sources, config):
  if config.rev == 'fail':
    raise ApacheThriftError('Failed to generate via apache thrift for '
                            'sources: {}, config: {}'.format(sources, config))
  if isinstance(config, ApacheThriftJavaConfiguration):
    return JavaSources(files=['Fake.java'], dependencies=config.dependencies)
  elif isinstance(config, ApacheThriftPythonConfiguration):
    return PythonSources(files=['fake.py'], dependencies=config.dependencies)


class BuildPropertiesConfiguration(Struct):
  pass


@rule(Classpath, [Select(BuildPropertiesConfiguration)])
@printing_func
def write_name_file(name):
  """Write a file containing the name of this target in the CWD."""
  return Classpath(creator='write_name_file')


class Scrooge(datatype('Scrooge', ['tool_address'])):
  """Placeholder for a Scrooge subsystem."""


class ScroogeConfiguration(ThriftConfiguration):
  def __init__(self, rev=None, strict=True, **kwargs):
    """
    :param string rev: The version of the scrooge compiler to use.
    :param bool strict: `False` to turn strict compiler warnings off (not recommended).
    """
    super(ScroogeConfiguration, self).__init__(rev=rev, strict=strict, **kwargs)


class ScroogeScalaConfiguration(ScroogeConfiguration):
  pass


class ScroogeJavaConfiguration(ScroogeConfiguration):
  pass


@rule(ScalaSources,
      [Select(ThriftSources),
       SelectVariant(ScroogeScalaConfiguration, 'thrift'),
       SelectProjection(Classpath, Address, 'tool_address', Scrooge)])
def gen_scrooge_scala_thrift(sources, config, scrooge_classpath):
  return gen_scrooge_thrift(sources, config, scrooge_classpath)


@rule(JavaSources,
      [Select(ThriftSources),
       SelectVariant(ScroogeJavaConfiguration, 'thrift'),
       SelectProjection(Classpath, Address, 'tool_address', Scrooge)])
def gen_scrooge_java_thrift(sources, config, scrooge_classpath):
  return gen_scrooge_thrift(sources, config, scrooge_classpath)


@printing_func
def gen_scrooge_thrift(sources, config, scrooge_classpath):
  if isinstance(config, ScroogeJavaConfiguration):
    return JavaSources(files=['Fake.java'], dependencies=config.dependencies)
  elif isinstance(config, ScroogeScalaConfiguration):
    return ScalaSources(files=['Fake.scala'], dependencies=config.dependencies)


@rule(Classpath,
      [Select(JavaSources),
       SelectDependencies(Classpath, JavaSources, field_types=(Address, Jar))])
@printing_func
def javac(sources, classpath):
  return Classpath(creator='javac')


@rule(Classpath,
      [Select(ScalaSources),
       SelectDependencies(Classpath, ScalaSources, field_types=(Address, Jar))])
@printing_func
def scalac(sources, classpath):
  return Classpath(creator='scalac')


class Goal(AbstractClass):
  """A synthetic aggregate product produced by a goal, which is its own task."""

  def __init__(self, *args):
    if all(arg is None for arg in args):
      msg = '\n  '.join(p.__name__ for p in self.products())
      raise TaskError('Unable to produce any of the products for goal `{}`:\n  {}'.format(
        self.name(), msg))

  @classmethod
  @abstractmethod
  def name(cls):
    """Returns the name of the Goal."""

  @classmethod
  def rule(cls):
    """Returns a Rule for this Goal, used to install the Goal.

    A Goal is it's own synthetic output product, and its constructor acts as its task function. It
    selects each of its products as optional, but fails synchronously if none of them are available.
    """
    return TaskRule(cls, [Select(p, optional=True) for p in cls.products()], cls)

  @classmethod
  @abstractmethod
  def products(cls):
    """Returns the products that this Goal requests."""

  def __eq__(self, other):
    return type(self) == type(other)

  def __ne__(self, other):
    return not (self == other)

  def __hash__(self):
    return hash(type(self))

  def __str__(self):
    return '{}()'.format(type(self).__name__)

  def __repr__(self):
    return str(self)


class GenGoal(Goal):
  """A goal that requests all known types of sources."""

  @classmethod
  def name(cls):
    return 'gen'

  @classmethod
  def products(cls):
    return [JavaSources, PythonSources, ResourceSources, ScalaSources]


class ExampleTable(SymbolTable):
  @classmethod
  def table(cls):
    return {'apache_thrift_java_configuration': ApacheThriftJavaConfiguration,
            'apache_thrift_python_configuration': ApacheThriftPythonConfiguration,
            'jar': Jar,
            'managed_jar': ManagedJar,
            'managed_resolve': ManagedResolve,
            'requirement': Requirement,
            'scrooge_java_configuration': ScroogeJavaConfiguration,
            'scrooge_scala_configuration': ScroogeScalaConfiguration,
            'java': JavaSources,
            'python': PythonSources,
            'resources': ResourceSources,
            'scala': ScalaSources,
            'thrift': ThriftSources,
            'target': Target,
            'variants': Variants,
            'build_properties': BuildPropertiesConfiguration,
            'inferred_scala': ScalaInferredDepsSources}


def setup_json_scheduler(build_root, native):
  """Return a build graph and scheduler configured for BLD.json files under the given build root.

  :rtype :class:`pants.engine.scheduler.LocalScheduler`
  """

  symbol_table_cls = ExampleTable

  # Register "literal" subjects required for these tasks.
  # TODO: Replace with `Subsystems`.
  address_mapper = AddressMapper(symbol_table_cls=symbol_table_cls,
                                 build_patterns=('BLD.json',),
                                 parser_cls=JsonParser)

  work_dir = os_path_join(build_root, '.pants.d')
  project_tree = FileSystemProjectTree(build_root)

  goals = {
      'compile': Classpath,
      # TODO: to allow for running resolve alone, should split out a distinct 'IvyReport' product.
      'resolve': Classpath,
      'list': BuildFileAddresses,
      GenGoal.name(): GenGoal,
      'ls': Snapshot,
      'cat': FilesContent,
    }
  tasks = [
      # Codegen
      GenGoal.rule(),
      gen_apache_java_thrift,
      gen_apache_python_thrift,
      gen_scrooge_scala_thrift,
      gen_scrooge_java_thrift,
      SingletonRule(Scrooge, Scrooge(Address.parse('src/scala/scrooge')))
    ] + [
      # scala dependency inference
      reify_scala_sources,
      extract_scala_imports,
      select_package_address,
      calculate_package_search_path,
      SingletonRule(SourceRoots, SourceRoots(('src/java','src/scala'))),
    ] + [
      # Remote dependency resolution
      ivy_resolve,
      select_rev,
    ] + [
      # Compilers
      isolate_resources,
      write_name_file,
      javac,
      scalac,
    ] + (
      create_graph_rules(address_mapper, symbol_table_cls)
    ) + (
      create_fs_rules()
    )

  return LocalScheduler(work_dir,
                        goals,
                        tasks,
                        project_tree,
                        native,
                        graph_lock=None)
