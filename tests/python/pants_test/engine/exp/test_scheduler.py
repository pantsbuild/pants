# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import os
import unittest

from twitter.common.collections.orderedset import OrderedSet

from pants.build_graph.address import Address
from pants.engine.exp.addressable import SubclassesOf, addressable_list
from pants.engine.exp.configuration import Configuration
from pants.engine.exp.graph import Graph
from pants.engine.exp.mapper import AddressMapper
from pants.engine.exp.parsers import parse_json
from pants.engine.exp.scheduler import (BuildRequest, GlobalScheduler, Plan, Planners, Promise,
                                        Subject, Task, TaskPlanner)
from pants.engine.exp.targets import Sources as AddressableSources
from pants.engine.exp.targets import Target
from pants.util.memo import memoized


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

  def __init__(self, org, name, rev=None, **kwargs):
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
    yield Classpath

  def plan(self, scheduler, product_type, subject):
    if isinstance(subject, Jar):
      # This plan is only used internally, the finalized plan will s/jar/jars/ for a single global
      # resolve.
      return Plan(task_type=IvyResolve, subjects=(subject,), jar=subject)

  def finalize_plans(self, plans):
    subjects = set()
    jars = OrderedSet()
    for plan in plans:
      subjects.update(plan.subjects)
      jars.add(plan.jar)
    global_plan = Plan(task_type=IvyResolve, subjects=subjects, jars=list(jars))
    return [global_plan]


class IvyResolve(Task):
  def execute(self, jars):
    pass


class Sources(object):
  @staticmethod
  @memoized
  def of(ext):
    return type(b'Sources({!r})'.format(ext), (Sources,), dict(ext=ext))

  @classmethod
  def ext(cls):
    raise NotImplementedError()


class ApacheThriftConfiguration(Configuration):
  def __init__(self, rev, gen, strict=True, deps=None, **kwargs):
    """
    :param string rev: The version of the apache thrift compiler to use.
    :param string gen: The thrift compiler `--gen` argument specifying the type of code to generate
                       and any options to pass to the generator.
    :param bool strict: `False` to turn strict compiler warnings off (not recommended).
    :param deps: An optional list of dependencies needed by the generated code.
    :type deps: list of jars
    """
    super(ApacheThriftConfiguration, self).__init__(rev=rev, gen=gen, strict=strict, **kwargs)
    self.deps = deps

  # Could be Jars, PythonRequirements, ... we simply don't know a-priori - depends on --gen lang.
  @addressable_list(SubclassesOf(Configuration))
  def deps(self):
    """Return a list of the dependencies needed by the generated code."""


class ApacheThriftPlanner(TaskPlanner):

  def __init__(self):
    # This will come via an option default.
    # TODO(John Sirois): once the options system is plumbed, make the languages configurable.
    self._product_type_by_lang = {'java': Sources.of('.java'), 'py': Sources.of('.py')}

  @property
  def goal_name(self):
    return 'gen'

  @property
  def product_types(self):
    return self._product_type_by_lang.values()

  def _product_type(self, gen):
    lang = gen.partition(':')[0]
    return self._product_type_by_lang.get(lang)

  def plan(self, scheduler, product_type, subject):
    if not isinstance(subject, Target):
      return None

    thrift_sources = list(subject.sources.iter_paths(base_path=subject.address.spec_path,
                                                     ext='.thrift'))
    if not thrift_sources:
      return None

    configs = [config for config in subject.configurations
               if product_type == self._product_type(config.gen)]
    if not configs:
      # We don't know how to generate these type of sources for this subject.
      return None
    if len(configs) > 1:
      raise self.Error('Found more than one configuration for generating {!r} from {!r}:\n\t{}'
                       .format(product_type, subject, '\n\t'.join(repr(c) for c in configs)))
    config = configs[0]

    subject = Subject(subject, alternate=Target(dependencies=config.deps))
    return Plan(task_type=ApacheThrift,
                subjects=(subject,),
                sources=thrift_sources,
                rev=config.rev,
                gen=config.gen,
                strict=config.strict)


class ApacheThrift(Task):
  def execute(self, sources, rev, gen, strict):
    pass


class JavacPlanner(TaskPlanner):
  # Product type
  JavaSources = Sources.of('.java')

  @property
  def goal_name(self):
    return 'compile'

  @property
  def product_types(self):
    yield Classpath

  def plan(self, scheduler, product_type, subject):
    if not isinstance(subject, Target):
      return None

    sources = list(subject.sources.iter_paths(base_path=subject.address.spec_path, ext='.java'))
    if not sources:
      # TODO(John Sirois): Abstract a ~SourcesConsumerPlanner that can grab sources of given types
      # or else defer to a code generator like we do here.  As it stands, the planner must
      # explicitly allow for code generators and this repeated code / foresight can easily be
      # missed in new compilers, and other source-using tasks.  Once done though, code gen can be
      # introduced to any nesting depth, ie: code gen '.thrift' files.

      # This is a dep graph "hole", we depend on the thing but don't know what it is.  Either it
      # could be something that gets transformed in to java or transformed into a `Classpath`
      # by some other compiler targeting the jvm.
      sources = scheduler.promise(subject, self.JavaSources, required=False)
      if sources:
        subject = sources.subject

    if not sources:
      # We don't know how to compile this subject, someone else may (Scalac, Groovyc, ...)
      return None

    classpath_promises = []
    for derivation in Subject.as_subject(subject).iter_derivations:
      for dep in derivation.dependencies:
        # This could recurse to us (or be satisfied by IvyResolve, Scalac, etc. depending on the
        # dep type).
        internal_cp_promise = scheduler.promise(dep, Classpath)
        if internal_cp_promise:
          classpath_promises.append(internal_cp_promise)

    return Plan(task_type=JavacTask,
                subjects=(subject,),
                sources=sources,
                classpath=classpath_promises)


class JavacTask(Task):
  def execute(self, sources, classpath):
    pass


class SchedulerTest(unittest.TestCase):
  def setUp(self):
    build_root = os.path.join(os.path.dirname(__file__), 'examples', 'scheduler_inputs')
    symbol_table = {'apache_thrift_configuration': ApacheThriftConfiguration,
                    'jar': Jar,
                    'requirement': Requirement,
                    'sources': AddressableSources,
                    'target': Target}
    json_parser = functools.partial(parse_json, symbol_table=symbol_table)
    self.graph = Graph(AddressMapper(build_root=build_root,
                                     build_pattern=r'^BLD.json$',
                                     parser=json_parser))

    self.guava = self.graph.resolve(Address.parse('3rdparty/jvm:guava'))
    self.thrift = self.graph.resolve(Address.parse('src/thrift/codegen/simple'))
    self.java = self.graph.resolve(Address.parse('src/java/codegen/simple'))

    planners = [ApacheThriftPlanner(), GlobalIvyResolvePlanner(), JavacPlanner()]
    self.global_scheduler = GlobalScheduler(self.graph, Planners(planners))

  def assert_resolve_only(self, goals, root_specs, jars):
    build_request = BuildRequest(goals=goals,
                                 addressable_roots=[Address.parse(spec) for spec in root_specs])
    execution_graph = self.global_scheduler.execution_graph(build_request)

    plans = list(execution_graph.walk())
    self.assertEqual(1, len(plans))
    self.assertEqual(Plan(task_type=IvyResolve, subjects=jars, jars=list(jars)), plans[0])

  def test_resolve(self):
    self.assert_resolve_only(goals=['resolve'],
                             root_specs=['3rdparty/jvm:guava'],
                             jars=[self.guava])

  def test_compile_only_3rdaprty(self):
    self.assert_resolve_only(goals=['compile'],
                             root_specs=['3rdparty/jvm:guava'],
                             jars=[self.guava])

  def test_gen_noop(self):
    # TODO(John Sirois): Ask around - is this OK?
    # This is different than today.  There is a gen'able target reachable from the java target, but
    # the scheduler 'pull-seeding' has ApacheThriftPlanner stopping short since the subject it's
    # handed is not thrift.
    build_request = BuildRequest(goals=['gen'], addressable_roots=[self.java.address])
    execution_graph = self.global_scheduler.execution_graph(build_request)

    plans = list(execution_graph.walk())
    self.assertEqual(0, len(plans))

  def test_gen(self):
    build_request = BuildRequest(goals=['gen'], addressable_roots=[self.thrift.address])
    execution_graph = self.global_scheduler.execution_graph(build_request)

    plans = list(execution_graph.walk())
    self.assertEqual(1, len(plans))

    self.assertEqual(Plan(task_type=ApacheThrift,
                          subjects=[self.thrift],
                          strict=True,
                          rev='0.9.2',
                          gen='java',
                          sources=['src/thrift/codegen/simple/simple.thrift']),
                     plans[0])

  def test_codegen_simple(self):
    build_request = BuildRequest(goals=['compile'], addressable_roots=[self.java.address])
    execution_graph = self.global_scheduler.execution_graph(build_request)

    plans = list(execution_graph.walk())
    self.assertEqual(4, len(plans))

    thrift_jars = [Jar(org='org.apache.thrift', name='libthrift', rev='0.9.2'),
                   Jar(org='commons-lang', name='commons-lang', rev='2.5'),
                   Jar(org='org.slf4j', name='slf4j-api', rev='1.6.1')]

    jars = [self.guava] + thrift_jars

    # Independent leaves 1st
    self.assertEqual({Plan(task_type=ApacheThrift,
                           subjects=[self.thrift],
                           strict=True,
                           rev='0.9.2',
                           gen='java',
                           sources=['src/thrift/codegen/simple/simple.thrift']),
                      Plan(task_type=IvyResolve, subjects=jars, jars=jars)},
                     set(plans[0:2]))

    # The rest is linked.
    self.assertEqual(Plan(task_type=JavacTask,
                          subjects=[self.thrift],
                          sources=Promise(Sources.of('.java'), self.thrift),
                          classpath=[Promise(Classpath, jar) for jar in thrift_jars]),
                     plans[2])

    self.assertEqual(Plan(task_type=JavacTask,
                          subjects=[self.java],
                          sources=['src/java/codegen/simple/Simple.java'],
                          classpath=[Promise(Classpath, self.guava),
                                     Promise(Classpath, self.thrift)]),
                     plans[3])
