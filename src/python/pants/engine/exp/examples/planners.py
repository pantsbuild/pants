# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
from abc import abstractmethod, abstractproperty

from twitter.common.collections import OrderedSet

from pants.base.exceptions import TaskError
from pants.build_graph.address import Address
from pants.engine.exp.addressable import SubclassesOf, addressable_list
from pants.engine.exp.configuration import Configuration
from pants.engine.exp.graph import Graph
from pants.engine.exp.mapper import AddressMapper
from pants.engine.exp.parsers import parse_json
from pants.engine.exp.products import Sources
from pants.engine.exp.scheduler import LocalScheduler, Plan, Planners, Subject, Task, TaskPlanner
from pants.engine.exp.targets import Sources as AddressableSources
from pants.engine.exp.targets import Target
from pants.util.memo import memoized, memoized_property


class PrintingTask(Task):
  @classmethod
  def fake_product(cls):
    return '<<<Fake{}Product>>>'.format(cls.__name__)

  def execute(self, **inputs):
    print('{} being executed with inputs: {}'.format(type(self).__name__, inputs))
    return self.fake_product()


def printing_func(func):
  @functools.wraps(func)
  def wrapper(**inputs):
    print('{} being executed with inputs: {}'.format(func.__name__, inputs))
    product = func(**inputs)
    return product if product else '<<<Fake{}Product>>>'.format(func.__name__)
  return wrapper


class Requirement(Configuration):
  """A setuptools requirement."""

  def __init__(self, req, repo=None, **kwargs):
    """
    :param string req: A setuptools compatible requirement specifier; eg: `pantsbuild.pants>0.0.42`.
    :param string repo: An optional custom find-links repo URL.
    """
    super(Requirement, self).__init__(req=req, repo=repo, **kwargs)


class Classpath(object):
  # Placeholder product.
  pass


class Jar(Configuration):
  """A java jar."""

  def __init__(self, org=None, name=None, rev=None, **kwargs):
    """
    :param string org: The Maven ``groupId`` of this dependency.
    :param string name: The Maven ``artifactId`` of this dependency; also serves as the name portion
                        of the address of this jar if defined at the top level of a BUILD file.
    :param string rev: The Maven ``version`` of this dependency.
    """
    super(Jar, self).__init__(org=org, name=name, rev=rev, **kwargs)


class GlobalIvyResolvePlanner(TaskPlanner):
  @property
  def goal_name(self):
    return 'resolve'

  @property
  def product_types(self):
    return {Classpath: [[Jar]]}

  def plan(self, scheduler, product_type, subject, configuration=None):
    if isinstance(subject, Jar):
      # This plan is only used internally, the finalized plan will s/jar/jars/ for a single global
      # resolve.
      return Plan(func_or_task_type=IvyResolve, subjects=(subject,), jar=subject)

  def finalize_plans(self, plans):
    subjects = set()
    jars = OrderedSet()
    for plan in plans:
      subjects.update(plan.subjects)
      jars.add(plan.jar)
    global_plan = Plan(func_or_task_type=IvyResolve, subjects=subjects, jars=list(jars))
    return [global_plan]


class IvyResolve(PrintingTask):
  def execute(self, jars):
    return super(IvyResolve, self).execute(jars=jars)


def _create_sources(ext):
  # A pickle-compatible top-level function for custom unpickling of Sources per-extension types.
  return Sources.of(ext)


class ThriftConfiguration(Configuration):
  def __init__(self, deps=None, **kwargs):
    """
    :param deps: An optional list of dependencies needed by the generated code.
    :type deps: list of jars
    """
    super(ThriftConfiguration, self).__init__(**kwargs)
    self.deps = deps

  # Could be Jars, PythonRequirements, ... we simply don't know a-priori - depends on --gen lang.
  @addressable_list(SubclassesOf(Configuration))
  def deps(self):
    """Return a list of the dependencies needed by the generated code."""


class ThriftPlanner(TaskPlanner):
  @property
  def goal_name(self):
    return 'gen'

  @abstractproperty
  def product_type_by_config_type(self):
    """A dict of configuration types to product types for this planner.

    # This will come via an option default.
    # TODO(John Sirois): once the options system is plumbed, make the languages configurable.
    """

  @abstractproperty
  def gen_func(self):
    """Return the code gen function.

    :rtype: function
    """

  @abstractmethod
  def plan_parameters(self, scheduler, product_type, subject, config):
    """Return a dict of any extra parameters besides `sources` needed to execute the code gen plan.

    :rtype: dict
    """

  @property
  def product_types(self):
    return {product_type: [[Sources.of('.thrift'), config_type]]
            for config_type, product_type in self.product_type_by_config_type.items()}

  def _extract_thrift_config(self, product_type, target, configuration=None):
    """Return the configuration to be used to produce the given product type for the given target.

    :rtype: :class:`ThriftConfiguration`
    """
    configs = (configuration,) if configuration else target.configurations
    configs = tuple(config for config in configs
                    if (product_type == self.product_type_by_config_type.get(type(config))))
    if not configs:
      # We don't know how to generate these type of sources for this subject.
      raise self.Error('No configuration for generating {!r} from {!r}.'.format(product_type, target))
    if len(configs) > 1:
      raise self.Error('Found more than one configuration for generating {!r} from {!r}:\n\t{}'
                       .format(product_type, target, '\n\t'.join(repr(c) for c in configs)))
    return configs[0]

  def plan(self, scheduler, product_type, subject, configuration=None):
    thrift_sources = list(subject.sources.iter_paths(base_path=subject.address.spec_path,
                                                     ext='.thrift'))
    if not thrift_sources:
      raise self.Error('No thrift sources for {!r} from {!r}.'.format(product_type, subject))

    config = self._extract_thrift_config(product_type, subject, configuration=configuration)
    subject = Subject(subject, alternate=Target(dependencies=config.deps))
    inputs = self.plan_parameters(scheduler, product_type, subject, config)
    return Plan(func_or_task_type=self.gen_func, subjects=(subject,), sources=thrift_sources, **inputs)


class ApacheThriftJavaConfiguration(ThriftConfiguration):
  def __init__(self, rev=None, strict=True, **kwargs):
    """
    :param string rev: The version of the apache thrift compiler to use.
    :param bool strict: `False` to turn strict compiler warnings off (not recommended).
    """
    super(ApacheThriftJavaConfiguration, self).__init__(rev=rev, strict=strict, **kwargs)

  @abstractproperty
  def gen(self):
    pass


class ApacheThriftJavaConfiguration(ThriftConfiguration):
  gen = 'java'


class ApacheThriftPythonConfiguration(ThriftConfiguration):
  gen = 'python'


class ApacheThriftPlanner(ThriftPlanner):
  @property
  def gen_func(self):
    return gen_apache_thrift

  @memoized_property
  def product_type_by_config_type(self):
    return {
        ApacheThriftJavaConfiguration: Sources.of('.java'),
        ApacheThriftPythonConfiguration: Sources.of('.py'),
      }

  def plan_parameters(self, scheduler, product_type, subject, apache_thrift_config):
    return dict(rev=apache_thrift_config.rev,
                gen=apache_thrift_config.gen,
                strict=apache_thrift_config.strict)


class ApacheThriftError(TaskError):
  pass


@printing_func
def gen_apache_thrift(sources, rev, gen, strict):
  if rev == 'fail':
    raise ApacheThriftError('Failed to generate via apache thrift for sources: {}, rev: {}, '
                            'gen:{}, strict: {}'.format(sources, rev, gen, strict))


class BuildPropertiesConfiguration(Configuration):
  pass


class BuildPropertiesPlanner(TaskPlanner):
  """A planner that adds a Classpath entry for all targets configured for build_properties.

  NB: In the absence of support for merging multiple Promises for a particular product_type,
  this serves as a valid example that explodes when it should succeed.
  """

  @property
  def goal_name(self):
    return None

  @property
  def product_types(self):
    return {Classpath: [[BuildPropertiesConfiguration]]}

  def plan(self, scheduler, product_type, subject, configuration=None):
    assert product_type == Classpath
    return Plan(func_or_task_type=write_name_file, subjects=(subject,), name=subject.name)


def write_name_file(name):
  # Write a file containing the name in CWD
  with safe_open('build.properties') as f:
    f.write('name={}\n'.format(name))


class ScroogeConfiguration(ThriftConfiguration):
  def __init__(self, rev=None, strict=True, **kwargs):
    """
    :param string rev: The version of the scrooge compiler to use.
    :param bool strict: `False` to turn strict compiler warnings off (not recommended).
    """
    super(ScroogeScalaConfiguration, self).__init__(rev=rev, strict=strict, **kwargs)

  @abstractproperty
  def lang(self):
    pass


class ScroogeScalaConfiguration(ThriftConfiguration):
  lang = 'scala'


class ScroogeJavaConfiguration(ThriftConfiguration):
  lang = 'java'


class ScroogePlanner(ThriftPlanner):
  @property
  def gen_func(self):
    return gen_scrooge_thrift

  @memoized_property
  def product_type_by_config_type(self):
    return {
        ScroogeJavaConfiguration: Sources.of('.java'),
        ScroogeScalaConfiguration: Sources.of('.scala'),
      }

  def plan_parameters(self, scheduler, product_type, subject, scrooge_config):
    # This will come via an option default.
    # TODO(John Sirois): once the options system is plumbed, make the tool spec configurable.
    # It could also just be pointed at the scrooge jar at that point.
    scrooge_classpath = scheduler.promise(Address.parse('src/scala/scrooge'), Classpath)
    return dict(scrooge_classpath=scrooge_classpath,
                lang=scrooge_config.lang,
                strict=scrooge_config.strict)


@printing_func
def gen_scrooge_thrift(sources, scrooge_classpath, lang, strict):
  pass


class JvmCompilerPlanner(TaskPlanner):
  @property
  def goal_name(self):
    return 'compile'

  @property
  def product_types(self):
    return {Classpath: [[Sources.of(self.source_ext)]]}

  @abstractproperty
  def compile_task_type(self):
    """Return the type of the jvm compiler task.

    :rtype: type
    """

  @abstractproperty
  def source_ext(self):
    """Return the extension of the source code compiled by the jvm compiler.

    :rtype: string
    """

  def plan(self, scheduler, product_type, subject, configuration=None):
    sources = list(subject.sources.iter_paths(base_path=subject.address.spec_path,
                                              ext=self.source_ext))
    if not sources:
      # TODO(John Sirois): Abstract a ~SourcesConsumerPlanner that can grab sources of given types
      # or else defer to a code generator like we do here.  As it stands, the planner must
      # explicitly allow for code generators and this repeated code / foresight can easily be
      # missed in new compilers, and other source-using tasks.  Once done though, code gen can be
      # introduced to any nesting depth, ie: code gen '.thrift' files.

      # This is a dep graph "hole", we depend on the thing but don't know what it is.  Either it
      # could be something that gets transformed in to our compile input source extension (codegen)
      # or transformed into a `Classpath` product by some other compiler targeting the jvm.
      sources = scheduler.promise(subject,
                                  Sources.of(self.source_ext),
                                  configuration=configuration)
      subject = sources.subject

    classpath_promises = []
    for dep, dep_config in self.iter_configured_dependencies(subject):
      # This could recurse to us (or be satisfied by IvyResolve, another jvm compiler, etc.
      # depending on the dep type).
      classpath = scheduler.promise(dep, Classpath, configuration=dep_config)
      classpath_promises.append(classpath)

    return Plan(func_or_task_type=self.compile_task_type,
                subjects=(subject,),
                sources=sources,
                classpath=classpath_promises)


class JavacPlanner(JvmCompilerPlanner):
  @property
  def source_ext(self):
    return '.java'

  @property
  def compile_task_type(self):
    return Javac


class Javac(PrintingTask):
  def execute(self, sources, classpath):
    return super(Javac, self).execute(sources=sources, classpath=classpath)


class ScalacPlanner(JvmCompilerPlanner):
  @property
  def source_ext(self):
    return '.scala'

  @property
  def compile_task_type(self):
    return Scalac


class Scalac(PrintingTask):
  def execute(self, sources, classpath):
    return super(Scalac, self).execute(sources=sources, classpath=classpath)


# TODO(John Sirois): When https://github.com/pantsbuild/pants/issues/2413 is resolved, move the
# unpickleable input and output test planners below to engine test.  There will be less setup
# required at that point since no target addresses will need to be supplied in the build_request.
class UnpickleableInputsPlanner(TaskPlanner):
  @property
  def goal_name(self):
    return 'unpickleable_inputs'

  @property
  def product_types(self):
    # A convenient product type only, will never be used outside engine internals.
    return {Sources.of('unpickleable_inputs'): [[]]}

  def plan(self, scheduler, product_type, subject, configuration=None):
    # Nested functions like this lambda are unpicklable.
    return Plan(lambda: None, (subject,))


def unpickable_result_func():
  # Nested functions like this lambda are unpicklable.
  return lambda: None


class UnpickleableResultPlanner(TaskPlanner):
  @property
  def goal_name(self):
    return 'unpickleable_result'

  @property
  def product_types(self):
    # A convenient product type only, will never be used outside engine internals.
    return {Sources.of('unpickleable_result'): [[Sources.of('unpickleable_inputs')]]}

  def plan(self, scheduler, product_type, subject, configuration=None):
    return Plan(unpickable_result_func, (subject,))


def setup_json_scheduler(build_root):
  """Return a build graph and scheduler configured for BLD.json files under the given build root.

  :rtype tuple of (:class:`pants.engine.exp.graph.Graph`,
                   :class:`pants.engine.exp.scheduler.LocalScheduler`)
  """
  symbol_table = {'apache_thrift_java_configuration': ApacheThriftJavaConfiguration,
                  'apache_thrift_python_configuration': ApacheThriftPythonConfiguration,
                  'jar': Jar,
                  'requirement': Requirement,
                  'scrooge_java_configuration': ScroogeJavaConfiguration,
                  'scrooge_scala_configuration': ScroogeScalaConfiguration,
                  'sources': AddressableSources,
                  'target': Target,
                  'build_properties': BuildPropertiesConfiguration}
  json_parser = functools.partial(parse_json, symbol_table=symbol_table)
  graph = Graph(AddressMapper(build_root=build_root,
                              build_pattern=r'^BLD.json$',
                              parser=json_parser))

  planners = Planners([ApacheThriftPlanner(),
                       BuildPropertiesPlanner(),
                       GlobalIvyResolvePlanner(),
                       JavacPlanner(),
                       ScalacPlanner(),
                       ScroogePlanner(),
                       UnpickleableInputsPlanner(),
                       UnpickleableResultPlanner()])
  scheduler = LocalScheduler(graph, planners)
  return graph, scheduler
