# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import collections
import inspect
from abc import abstractmethod, abstractproperty
from collections import defaultdict, namedtuple

import six
from twitter.common.collections import OrderedSet

from pants.build_graph.address import Address
from pants.engine.exp.addressable import extract_config_selector
from pants.engine.exp.objects import Serializable
from pants.util.memo import memoized_property
from pants.util.meta import AbstractClass


class Subject(object):
  """The subject of a production plan."""

  @classmethod
  def as_subject(cls, item):
    """Return the given item as the primary of a subject if its not already a subject.

    :rtype: :class:`Subject`
    """
    return item if isinstance(item, Subject) else cls(primary=item)

  def __init__(self, primary, alternate=None):
    """
    :param primary: The primary subject of a production plan.
    :param alternate: An alternate subject as suggested by some other plan.
    """
    self._primary = primary
    self._alternate = alternate

  @property
  def primary(self):
    """Return the primary subject."""
    return self._primary

  @property
  def iter_derivations(self):
    """Iterates over all subjects.

    The primary subject will always be returned as the 1st item from the iterator and if there is
    an alternate, it will be returned next.

    :rtype: :class:`collection.Iterator`
    """
    yield self._primary
    if self._alternate:
      yield self._alternate

  def __hash__(self):
    return hash(self._primary)

  def __eq__(self, other):
    return isinstance(other, Subject) and self._primary == other._primary

  def __ne__(self, other):
    return not (self == other)

  def __repr__(self):
    return 'Subject(primary={!r}, alternate={!r})'.format(self._primary, self._alternate)


class Binding(namedtuple('Binding', ['func', 'args', 'kwargs'])):
  """A binding for a plan that can be executed."""

  def execute(self):
    """Execute this binding and return the result."""
    return self.func(*self.args, **self.kwargs)


class TaskCategorization(namedtuple('TaskCategorization', ['func', 'task_type'])):
  """An Either type for a function or `Task` type."""

  @classmethod
  def of_func(cls, func):
    return cls(func=func, task_type=None)

  @classmethod
  def of_task_type(cls, task_type):
    return cls(func=None, task_type=task_type)

  @property
  def value(self):
    """Return the underlying func or task type.

    :rtype: function|type
    """
    return self.func or self.task_type


def _categorize(func_or_task_type):
  if isinstance(func_or_task_type, TaskCategorization):
    return func_or_task_type
  elif inspect.isclass(func_or_task_type):
    if not issubclass(func_or_task_type, Task):
      raise ValueError('A task must be a function or else a subclass of Task, given type {}'
                       .format(func_or_task_type.__name__))
    return TaskCategorization.of_task_type(func_or_task_type)
  else:
    return TaskCategorization.of_func(func_or_task_type)


def _execute_binding(categorization, **kwargs):
  # A picklable top-level function to help support local multiprocessing uses.
  # TODO(John Sirois): Plumb (context, workdir) or equivalents to the task_type constructor if
  # maintaining Task as a bridge to convert old style tasks makes sense.  Otherwise, simplify
  # things and only accept a func.
  function = categorization.func if categorization.func else categorization.task_type().execute
  return function(**kwargs)


class Plan(Serializable):
  """Represents an production plan that will yield a given product type for one or more subjects.

  A plan can be serialized and executed wherever its task type and and source inputs it needs are
  available.
  """
  # TODO(John Sirois): Sources are currently serialized as paths relative to the build root, but
  # they could also be serialized a a path + blob.  Talks about distributed backend solutions will
  # shake out if we need this in the near term.  Even if we only need paths for remote execution,
  # it probably makes sense to ship a path + hash pair so a remote build can fail fast if its source
  # inputs don't match local expectations.
  # NB: We don't ship around toolchains, just requirements of them as specified in plan inputs, like
  # the apache thrift compiler version.  There may need to be a protocol as a result that
  # pre-screens remote nodes for the capability to execute a given plan in-general (some nodes may
  # have a required toolchain but some may not and pants may have no intrinsic to fetch the
  # toolchain).  For example, pants can intrinsically fetch the Go toolchain in a Task today but it
  # cannot do the same for the jdk and instead only asserts its presence.

  def __init__(self, func_or_task_type, subjects, **inputs):
    """
    :param type func_or_task_type: The function that will execute this plan or else a :class:`Task`
                                   subclass.
    :param subjects: The subjects the plan will generate products for.
    :type subjects: :class:`collections.Iterable` of :class:`Subject` or else objects that will
                    be converted to the primary of a `Subject`.
    """
    self._func_or_task_type = _categorize(func_or_task_type)
    self._subjects = frozenset(Subject.as_subject(subject) for subject in subjects)
    self._inputs = inputs

  @property
  def func_or_task_type(self):
    """Return the function or `Task` type that will execute this plan.

    :rtype: :class:`TaskCategorization`
    """
    return self._func_or_task_type

  @property
  def subjects(self):
    """Return the subjects of this plan.

    When the plan is executed, its results will be associated with each one of these subjects.

    :rtype: frozenset of :class:`Subject`
    """
    return self._subjects

  def __getattr__(self, item):
    if item in self._inputs:
      return self._inputs[item]
    raise AttributeError('{} does not have attribute {!r}'.format(self, item))

  @staticmethod
  def _is_mapping(value):
    return isinstance(value, collections.Mapping)

  @staticmethod
  def _is_iterable(value):
    return isinstance(value, collections.Iterable) and not isinstance(value, six.string_types)

  @memoized_property
  def promises(self):
    """Return an iterator over the unique promises in this plan's inputs.

    A plan's promises indicate its dependency edges on other plans.

    :rtype: :class:`collections.Iterator` of :class:`Promise`
    """
    def iter_promises(item):
      if isinstance(item, Promise):
        yield item
      elif self._is_mapping(item):
        for _, v in item.items():
          for p in iter_promises(v):
            yield p
      elif self._is_iterable(item):
        for i in item:
          for p in iter_promises(i):
            yield p

    promises = set()
    for _, value in self._inputs.items():
      promises.update(iter_promises(value))
    return promises

  def bind(self, products_by_promise):
    """Bind this plans inputs to functions arguments.

    :param products_by_promise: A mapping containing this plan's satisfied promises.
    :type products_by_promise: dict of (:class:`Promise`, product)
    :returns: A binding for this plan to the given satisfied promises.
    :rtype: :class:`Binding`
    """
    def bind_products(item):
      if isinstance(item, Promise):
        return products_by_promise[item]
      elif self._is_mapping(item):
        return {k: bind_products(v) for k, v in item.items()}
      elif self._is_iterable(item):
        return [bind_products(i) for i in item]
      else:
        return item

    inputs = {}
    for key, value in self._inputs.items():
      inputs[key] = bind_products(value)

    return Binding(_execute_binding, args=(self._func_or_task_type,), kwargs=inputs)

  def _asdict(self):
    d = self._inputs.copy()
    d.update(func_or_task_type=self._func_or_task_type, subjects=tuple(self._subjects))
    return d

  def _key(self):
    def hashable(value):
      if self._is_mapping(value):
        return tuple(sorted((k, hashable(v)) for k, v in value.items()))
      elif self._is_iterable(value):
        return tuple(hashable(v) for v in value)
      else:
        return value
    return self._func_or_task_type, self._subjects, hashable(self._inputs)

  def __hash__(self):
    return hash(self._key())

  def __eq__(self, other):
    return isinstance(other, Plan) and self._key() == other._key()

  def __ne__(self, other):
    return not (self == other)

  def __repr__(self):
    return ('Plan(func_or_task_type={!r}, subjects={!r}, inputs={!r})'
            .format(self._func_or_task_type, self._subjects, self._inputs))


class SchedulingError(Exception):
  """Indicates inability to make a required scheduling promise."""


class NoProducersError(SchedulingError):
  """Indicates no planners were able to promise a required product for a given subject."""

  def __init__(self, product_type, subject=None):
    msg = ('No plans to generate {!r}{} could be made.'
            .format(product_type.__name__, ' {!r}'.format(subject) if subject else ''))
    super(NoProducersError, self).__init__(msg)


class ConflictingProducersError(SchedulingError):
  """Indicates more than one planner was able to promise a product for a given subject."""

  def __init__(self, product_type, subject, planners):
    msg = ('Collected the following plans for generating {!r} from {!r}\n\t{}'
            .format(product_type.__name__,
                    subject,
                    '\n\t'.join(type(p).__name__ for p in planners)))
    super(ConflictingProducersError, self).__init__(msg)


class Scheduler(AbstractClass):
  """Schedule the creation of products."""

  @abstractmethod
  def promise(self, subject, product_type, configuration=None, required=True):
    """Return an promise for a product of the given `product_type` for the given `subject`.

    The subject can either be a :class:`pants.engine.exp.objects.Serializable` object or else an
    :class:`Address`, in which case the promise subject is the addressable, serializable object it
    points to.

    If a configuration is supplied, the promise is for the requested product in that configuration.

    If the promise is required and no production plans can be made a
    :class:`Scheduler.SchedulingError` is raised.

    :param object subject: The subject that the product type should be created for.
    :param type product_type: The type of product to promise production of for the given subject.
    :param object configuration: An optional requested configuration for the product.
    :param bool required: `False` if the product is not required; `True` by default.
    :returns: A promise to make the given product type available for subject at task execution time
              or None if the promise was not required and no production plans could be made.
    :rtype: :class:`Promise`
    :raises: :class:`SchedulerError` if the promise was required and no production plans could be
             made.
    """


class TaskPlanner(AbstractClass):
  """Produces plans to control execution of a paired task."""

  class Error(Exception):
    """Indicates an error creating a product plan for a subject."""

  @classmethod
  def iter_configured_dependencies(cls, subject):
    """Return an iterator of the given subject's dependencies including any selected configurations.

    If no configuration is selected by a dependency (there is no `@[config-name]` specifier suffix),
    then `None` is returned for the paired configuration object; otherwise the `[config-name]` is
    looked for in the subject `configurations` list and returned if found or else an error is
    raised.

    :returns: An iterator over subjects dependencies as pairs of (dependency, configuration).
    :rtype: :class:`collections.Iterator` of (object, string)
    :raises: :class:`TaskPlanner.Error` if a dependency configuration was selected by subject but
             could not be found or was not unique.
    """
    for derivation in Subject.as_subject(subject).iter_derivations:
      if derivation.dependencies:
        for dep in derivation.dependencies:
          configuration = None
          if dep.address:
            config_specifier = extract_config_selector(dep.address)
            if config_specifier:
              if not dep.configurations:
                raise cls.Error('The dependency of {dependee} on {dependency} selects '
                                'configuration {config} but {dependency} has no configurations.'
                                .format(dependee=derivation,
                                        dependency=dep,
                                        config=config_specifier))
              configuration = dep.select_configuration(config_specifier)
          yield dep, configuration

  @abstractproperty
  def goal_name(self):
    """Return the name of the goal this planner's task should run from.

    :rtype: string
    """

  # TODO(John Sirois): This method is only needed to short-circuit asking every planner for every
  # promise request, perhaps kill this and/or do a perf compare and drop if negligible.  Right now
  # it's boilerplate that can be done wrong.
  @abstractproperty
  def product_types(self):
    """Return an iterator over the product types this planner's task can produce."""

  @abstractmethod
  def plan(self, scheduler, product_type, subject, configuration=None):
    """
    :param scheduler: A scheduler that can supply promises for any inputs needed that the planner
                      cannot supply on its own to its associated task.
    :type scheduler: :class:`Scheduler`
    :param type product_type: The type of product this plan should produce given subject when
                              executed.
    :param object subject: The subject of the plan.  Any products produced will be for the subject.
    :param object configuration: An optional requested configuration for the product.
    """

  def finalize_plans(self, plans):
    """Subclasses can override to finalize the plans they created.

    :param plans: All the plans emitted by this planner for the current planning session.
    :type plans: :class:`collections.Iterable` of :class:`Plan`
    :returns: A possibly different iterable of plans.
    :rtype: :class:`collections.Iterable` of :class:`Plan`
    """
    return plans


class Task(object):
  """An executable task.

  Tasks form the atoms of work done by pants and when executed generally produce artifacts as a
  side effect whether these be files on disk (for example compilation outputs) or characters output
  to the terminal (for example dependency graph metadata).  These outputs are always represented
  by a product type - sometimes `None`.  The product type instances the task returns can often be
  used to access the contents side-effect outputs.
  """

  def execute(self, **inputs):
    """Executes this task."""


class Planners(object):
  """A registry of task planners indexed by both product type and goal name."""

  def __init__(self, planners):
    """
    :param planners: All the task planners registered in the system.
    :type planners: :class:`collections.Iterable` of :class:`TaskPlanner`
    """
    self._planners_by_goal_name = defaultdict(set)
    self._planners_by_product_type = defaultdict(set)
    for planner in planners:
      self._planners_by_goal_name[planner.goal_name].add(planner)
      for product_type in planner.product_types:
        self._planners_by_product_type[product_type].add(planner)

  def for_goal(self, goal_name):
    """Return the set of task planners installed in the given goal.

    :param string goal_name:
    :rtype: set of :class:`TaskPlanner`
    """
    return self._planners_by_goal_name[goal_name]

  def for_product_type(self, product_type):
    """Return the set of task planners that can produce the given product type.

    :param type product_type: The product type the returned planners are capable of producing.
    :rtype: set of :class:`TaskPlanner`
    """
    return self._planners_by_product_type[product_type]


class BuildRequest(object):
  """Describes the user-requested build."""

  def __init__(self, goals, addressable_roots):
    """
    :param goals: The list of goal names supplied on the command line.
    :type goals: list of string
    :param addressable_roots: The list of addresses supplied on the command line.
    :type addressable_roots: list of :class:`pants.build_graph.address.Address`
    """
    self._goals = goals
    self._addressable_roots = addressable_roots

  @property
  def goals(self):
    """Return the list of goal names supplied on the command line.

    :rtype: list of string
    """
    return self._goals

  @property
  def addressable_roots(self):
    """Return the list of addresses supplied on the command line.

    :rtype: list of :class:`pants.build_graph.address.Address`
    """
    return self._addressable_roots

  def __repr__(self):
    return ('BuildRequest(goals={!r}, addressable_roots={!r})'
            .format(self._goals, self._addressable_roots))


class ExecutionGraph(object):
  """A DAG of execution plans where edges represent data dependencies between plans."""

  def __init__(self, root_promises, product_mapper):
    """
    :param root_promises: The root promises in the graph; these represent the final products
                          requested.
    :type root_promises: :class:`collections.Iterable` of :class:`Promise`
    :param product_mapper: A registry of all plans in the execution graph that will be used to
                           traverse from one plan's promises to the plans that will fulfill them
                           when executed.
    :type product_mapper: :class:`ProductMapper`
    """
    self._root_promises = root_promises
    self._product_mapper = product_mapper

  @property
  def root_promises(self):
    """Return the root promises in the graph.

    These represent the final products requested to satisfy a build request.

    :rtype: :class:`collections.Iterable` of :class:`Promise`
    """
    return self._root_promises

  def walk(self):
    """Performs a depth first post-order walk of the graph of execution plans.

    All plans are visited exactly once.

    :returns: A tuple of the product type the plan will produce when executed and the plan itself.
    :rtype tuple of (type, :class:`Plan`)
    """
    plans = set()
    for root_promise in self._root_promises:
      for promise, plan in self._walk_plan(root_promise, plans):
        yield promise, plan

  def _walk_plan(self, promise, plans):
    plan = self._product_mapper.promised(promise)
    if plan not in plans:
      plans.add(plan)
      for pr in plan.promises:
        for pl in self._walk_plan(pr, plans):
          yield pl
      yield promise, plan


class Promise(object):
  """Represents a promise to produce a given product type for a given subject."""

  def __init__(self, product_type, subject, configuration=None):
    """
    :param type product_type: The type of product promised.
    :param subject: The subject the product will be produced for; ie: a java library would be a
                    natural subject for a request for classfile products.
    :type subject: :class:`Subject` or else any object that will be the primary of the stored
                   `Subject`.
    :param object configuration: An optional promised configuration for the product.
    """
    self._product_type = product_type
    self._subject = Subject.as_subject(subject)
    self._configuration = configuration

  @property
  def product_type(self):
    """Return the type of product promised.

    :rtype: type
    """
    return self._product_type

  @property
  def subject(self):
    """Return the subject of this promise.

    :rtype: :class:`Subject`
    """
    return self._subject

  def rebind(self, subject):
    """Return a version of this promise bound to the new subject.

    :param subject: The new subject of the promise.
    :type subject: :class:`Subject` or else any object that will be the primary of the stored
                   `Subject`.
    :rtype: :class:`Promise`
    """
    return Promise(self._product_type, subject, configuration=self._configuration)

  def _key(self):
    # We promise the product_type for the primary subject, the alternate does not affect
    # consume-side identity.
    return self._product_type, self._subject.primary, self._configuration

  def __hash__(self):
    return hash(self._key())

  def __eq__(self, other):
    return isinstance(other, Promise) and self._key() == other._key()

  def __ne__(self, other):
    return not (self == other)

  def __repr__(self):
    return ('Promise(product_type={!r}, subject={!r}, configuration={!r})'
            .format(self._product_type, self._subject, self._configuration))


class ProductMapper(object):
  """Stores the mapping from promises to the plans whose execution will satisfy them."""

  class InvalidRegistrationError(Exception):
    """Indicates registration of a plan that does not cover the expected subject."""

  def __init__(self):
    self._promises = {}

  def register_promises(self, product_type, plan, primary_subject=None, configuration=None):
    """Registers the promises the given plan will satisfy when executed.

    :param type product_type: The product type the plan will produce when executed.
    :param plan: The plan to register promises for.
    :type plan: :class:`Plan`
    :param primary_subject: An optional primary subject.  If supplied, the registered promise for
                            this subject will be returned.
    :param object configuration: An optional promised configuration.
    :returns: The promise for the primary subject of one was supplied.
    :rtype: :class:`Promise`
    :raises: :class:`ProductMapper.InvalidRegistrationError` if a primary subject was supplied but
             not a member of the given plan's subjects.
    """
    # Index by all subjects.  This allows dependencies on products from "chunking" tasks, even
    # products from tasks that act globally in the extreme.
    primary_promise = None
    for subject in plan.subjects:
      promise = Promise(product_type, subject, configuration=configuration)
      if primary_subject == subject.primary:
        primary_promise = promise
      self._promises[promise] = plan

    if primary_subject and not primary_promise:
      raise self.InvalidRegistrationError('The subject {} is not part of the final plan!: {}'
                                          .format(primary_subject, plan))
    return primary_promise

  def promised(self, promise):
    """Return the plan that was promised.

    :param promise: The promise to lookup a registered plan for.
    :type promise: :class:`Promise`
    :returns: The plan registered for the given promise; or `None`.
    :rtype: :class:`Plan`
    """
    return self._promises.get(promise)


class LocalScheduler(Scheduler):
  """A scheduler that formulates an execution graph locally."""

  def __init__(self, graph, planners):
    """
    :param graph: The BUILD graph build requests will execute against.
    :type graph: :class:`pants.engine.exp.graph.Graph`
    :param planners: All the task planners known to the system.
    :type planners: :class:`Planners`
    """
    self._graph = graph
    self._planners = planners
    self._product_mapper = ProductMapper()
    self._plans_by_product_type_by_planner = defaultdict(lambda: defaultdict(OrderedSet))

  def execution_graph(self, build_request):
    """Create an execution graph that can satisfy the given build request.

    :param build_request: The description of the goals to achieve.
    :type build_request: :class:`BuildRequest`
    :returns: An execution graph of plans that, when reduced, can satisfy the given build request.
    :rtype: :class:`ExecutionGraph`
    :raises: :class:`LocalScheduler.SchedulingError` if no execution graph solution could be found.
    """
    goals = build_request.goals
    subjects = [self._graph.resolve(a) for a in build_request.addressable_roots]

    root_promises = []
    for goal in goals:
      for planner in self._planners.for_goal(goal):
        for product_type in planner.product_types:
          # TODO(John Sirois): Allow for subject-less (target-less) goals.  Examples are clean-all,
          # ng-killall, and buildgen.go.
          #
          # 1. If not subjects check for a special Planner subtype with a special subject-less
          #    promise method.
          # 2. Use a sentinel NO_SUBJECT, planners that care test for this, other planners that
          #    looks for Target or Jar or ... will naturally just skip it and no-op.
          #
          # Option 1 allows for failing the build if no such subtypes are amongst the goals;
          # ie: `./pants compile` would fail since there are no inputs and all compile registered
          # planners require subjects (don't implement the subtype).
          # Seems promising - but what about mixed goals and no subjects?
          #
          # What about if subjects but the planner doesn't care about them?  Is using the IvyGlobal
          # trick good enough here?  That pattern with fake Plans to aggregate could be packaged in
          # a TaskPlanner baseclass.
          for subject in subjects:
            promise = self.promise(subject, product_type, required=False)
            if promise:
              root_promises.append(promise)

    # Give aggregating planners a chance to aggregate plans.
    for planner, plans_by_product_type in self._plans_by_product_type_by_planner.items():
      for product_type, plans in plans_by_product_type.items():
        finalized_plans = planner.finalize_plans(plans)
        if finalized_plans is not plans:
          for finalized_plan in finalized_plans:
            self._product_mapper.register_promises(product_type, finalized_plan)

    return ExecutionGraph(root_promises, self._product_mapper)

  # A sentinel that denotes a `None` planning result that was accepted.  This can happen for
  # promise requests that are not required.
  NO_PLAN = Plan(func_or_task_type=None, subjects=())

  def promise(self, subject, product_type, configuration=None, required=True):
    if isinstance(subject, Address):
      subject = self._graph.resolve(subject)

    promise = Promise(product_type, subject, configuration=configuration)
    plan = self._product_mapper.promised(promise)
    if plan is not None:
      # The `NO_PLAN` plan may have been decided in a non-required round.
      if required and promise is self.NO_PLAN:
        raise NoProducersError(product_type, subject)
      return None if promise is self.NO_PLAN else promise

    planners = self._planners.for_product_type(product_type)
    if required and not planners:
      raise NoProducersError(product_type)

    plans = []
    for planner in planners:
      plan = planner.plan(self, product_type, subject, configuration=configuration)
      if plan:
        plans.append((planner, plan))

    if len(plans) > 1:
      planners = [planner for planner, plan in plans]
      raise ConflictingProducersError(product_type, subject, planners)
    elif not plans:
      if required:
        raise NoProducersError(product_type, subject)
      self._product_mapper.register_promises(product_type, self.NO_PLAN)
      return None

    planner, plan = plans[0]
    try:
      primary_promise = self._product_mapper.register_promises(product_type, plan,
                                                               primary_subject=subject,
                                                               configuration=configuration)
      self._plans_by_product_type_by_planner[planner][product_type].add(plan)
      return primary_promise
    except ProductMapper.InvalidRegistrationError:
      raise SchedulingError('The plan produced for {subject!r} by {planner!r} does not cover '
                            '{subject!r}:\n\t{plan!r}'.format(subject=subject,
                                                              planner=type(planner).__name__,
                                                              plan=plan))
