# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import collections
import functools
import os
import re
from abc import abstractmethod, abstractproperty

from pants.base.exceptions import TaskError
from pants.build_graph.address import Address
from pants.engine.exp.graph import Directory, create_graph_tasks
from pants.engine.exp.mapper import AddressFamily, AddressMapper
from pants.engine.exp.objects import datatype
from pants.engine.exp.parsers import JsonParser, SymbolTable
from pants.engine.exp.scheduler import (LocalScheduler, Select, SelectDependencies, SelectLiteral,
                                        SelectVariant)
from pants.engine.exp.struct import Struct, StructWithDeps
from pants.engine.exp.targets import Sources, Target, Variants
from pants.util.meta import AbstractClass


def printing_func(func):
  @functools.wraps(func)
  def wrapper(*inputs):
    product = func(*inputs)
    return_val = product if product else '<<<Fake-{}-Product>>>'.format(func.__name__)
    print('{} executed for {}, returned: {}'.format(func.__name__, inputs, return_val))
    return return_val
  return wrapper


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


class SourceRoots(datatype('SourceRoots', ['buildroot', 'srcroots'])):
  """Placeholder for the SourceRoot subsystem."""
  pass


class SearchPath(datatype('SearchPath', ['dependencies'])):
  """A set of Directories to search."""
  pass


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
  return addresses[0]


@printing_func
def calculate_package_search_path(jvm_package_name, source_roots):
  """Return a SearchPath for all directories where the given JVMPackageName might exist."""
  rel_package_dir = jvm_package_name.name.replace('.', os.sep)
  return SearchPath([Directory(os.path.join(srcroot, rel_package_dir))
                     for srcroot in source_roots.srcroots])


@printing_func
def extract_scala_imports(address, sources, source_roots):
  """A toy example of dependency inference. Would usually be a compiler plugin."""
  abs_base_path = os.path.join(source_roots.buildroot, address.spec_path)
  packages = set()
  import_re = re.compile(r'^import ([^;]*);?$')
  for f in sources.iter_paths(base_path=abs_base_path):
    with open(f) as source_file:
      for line in source_file:
        match = import_re.search(line)
        if match:
          packages.add(match.group(1).rsplit('.', 1)[0])
  return ImportedJVMPackages([JVMPackageName(p) for p in packages])


@printing_func
def reify_scala_sources(address, sources, dependency_addresses):
  return ScalaSources(files=list(sources.iter_paths(base_path=address.spec_path)),
                      dependencies=list(set(dependency_addresses)))


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


@printing_func
def select_rev(managed_jar, managed_resolve):
  (org, name) = (managed_jar.org, managed_jar.name)
  rev = managed_resolve.revs.get('{}#{}'.format(org, name), None)
  if not rev:
    raise TaskError('{} does not have a managed version in {}.'.format(managed_jar, managed_resolve))
  return Jar(org=managed_jar.org, name=managed_jar.name, rev=rev)


@printing_func
def ivy_resolve(jars):
  return Classpath(creator='ivy_resolve')


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


@printing_func
def write_name_file(name):
  """Write a file containing the name of this target in the CWD."""
  return Classpath(creator='write_name_file')


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


@printing_func
def gen_scrooge_thrift(sources, config, scrooge_classpath):
  if isinstance(config, ScroogeJavaConfiguration):
    return JavaSources(files=['Fake.java'], dependencies=config.dependencies)
  elif isinstance(config, ScroogeScalaConfiguration):
    return ScalaSources(files=['Fake.scala'], dependencies=config.dependencies)


@printing_func
def javac(sources, classpath):
  return Classpath(creator='javac')


@printing_func
def scalac(sources, classpath):
  return Classpath(creator='scalac')


# TODO(John Sirois): When https://github.com/pantsbuild/pants/issues/2413 is resolved, move the
# unpickleable input and output test planners below to engine test.  There will be less setup
# required at that point since no target addresses will need to be supplied in the build_request.
class UnpickleableOutput(object):
  pass


class UnpickleableResult(object):
  pass


def unpickleable_output():
  """Generates an unpickleable output."""
  # Nested functions like this lambda are unpicklable.
  return lambda: None


def unpickleable_input(unpickleable):
  raise Exception('This function should never run, because its selected input is unpickleable.')


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
  def signature(cls):
    """Returns a task triple for this Goal."""
    return (cls, [Select(p, optional=True) for p in cls.products()], cls)

  @classmethod
  @abstractmethod
  def products(cls):
    """Returns the products for this goal."""

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


def setup_json_scheduler(build_root):
  """Return a build graph and scheduler configured for BLD.json files under the given build root.

  :rtype :class:`pants.engine.exp.scheduler.LocalScheduler`
  """
  address_mapper = AddressMapper(build_root=build_root,
                                 symbol_table_cls=ExampleTable,
                                 build_pattern=r'^BLD.json$',
                                 parser_cls=JsonParser)

  # TODO(John Sirois): once the options system is plumbed, make the tool spec configurable.
  # It could also just be pointed at the scrooge jar at that point.
  scrooge_tool_address = Address.parse('src/scala/scrooge')

  # TODO: Placeholder for the SourceRoot subsystem.
  source_roots = SourceRoots(build_root, ('src/java',))

  goals = {
      'compile': Classpath,
      # TODO: to allow for running resolve alone, should split out a distinct 'IvyReport' product.
      'resolve': Classpath,
      GenGoal.name(): GenGoal,
      'unpickleable': UnpickleableResult,
    }
  tasks = [
      # Codegen
      GenGoal.signature(),
      (JavaSources,
       [Select(ThriftSources),
        SelectVariant(ApacheThriftJavaConfiguration, 'thrift')],
       gen_apache_thrift),
      (PythonSources,
       [Select(ThriftSources),
        SelectVariant(ApacheThriftPythonConfiguration, 'thrift')],
       gen_apache_thrift),
      (ScalaSources,
       [Select(ThriftSources),
        SelectVariant(ScroogeScalaConfiguration, 'thrift'),
        SelectLiteral(scrooge_tool_address, Classpath)],
       gen_scrooge_thrift),
      (JavaSources,
       [Select(ThriftSources),
        SelectVariant(ScroogeJavaConfiguration, 'thrift'),
        SelectLiteral(scrooge_tool_address, Classpath)],
       gen_scrooge_thrift),
    ] + [
      # scala dependency inference
      (ScalaSources,
       [Select(Address),
        Select(ScalaInferredDepsSources),
        SelectDependencies(Address, ImportedJVMPackages)],
       reify_scala_sources),
      (ImportedJVMPackages,
       [Select(Address),
        Select(ScalaInferredDepsSources),
        SelectLiteral(source_roots, SourceRoots)],
       extract_scala_imports),
      # TODO: The request for an AddressFamily for each member of a SearchPath will fail whenever
      # a member of the path doesn't exist. Need to allow for optional products and to then
      # request the AddressFamilies optionally here.
      (Address,
       [Select(JVMPackageName),
        SelectDependencies(AddressFamily, SearchPath)],
       select_package_address),
      (SearchPath,
       [Select(JVMPackageName),
        SelectLiteral(source_roots, SourceRoots)],
       calculate_package_search_path),
    ] + [
      # Remote dependency resolution
      (Classpath,
       [Select(Jar)],
       ivy_resolve),
      (Jar,
       [Select(ManagedJar),
        SelectVariant(ManagedResolve, 'resolve')],
       select_rev),
    ] + [
      # Compilers
      (Classpath,
       [Select(ResourceSources)],
       isolate_resources),
      (Classpath,
       [Select(BuildPropertiesConfiguration)],
       write_name_file),
      (Classpath,
       [Select(JavaSources),
        SelectDependencies(Classpath, JavaSources)],
       javac),
      (Classpath,
       [Select(ScalaSources),
        SelectDependencies(Classpath, ScalaSources)],
       scalac),
    ] + [
      # TODO
      (UnpickleableOutput,
        [],
        unpickleable_output),
      (UnpickleableResult,
       [Select(UnpickleableOutput)],
       unpickleable_input),
    ] + (
      create_graph_tasks(address_mapper)
    )

  scheduler = LocalScheduler(goals, ExampleTable, tasks)
  return scheduler
