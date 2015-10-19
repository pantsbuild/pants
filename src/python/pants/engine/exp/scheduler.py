# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import collections
import functools
import inspect
import multiprocessing
import Queue
from abc import abstractmethod, abstractproperty
from collections import defaultdict, namedtuple
from threading import Thread

import six
from twitter.common.collections import OrderedSet

from pants.base.exceptions import TaskError
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


def _execute_binding(func_or_task_type, **kwargs):
  # A picklable top-level function to help support local multiprocessing uses.
  if inspect.isclass(func_or_task_type):
    if not issubclass(func_or_task_type, Task):
      raise ValueError()  # TODO(John Sirois): XXX fixme
    function = func_or_task_type().execute
  else:
    function = func_or_task_type
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

  def __init__(self, task_type, subjects, **inputs):
    """
    :param type task_type: The type of :class:`Task` that will execute this plan.
    :param subjects: The subjects the plan will generate products for.
    :type subjects: :class:`collections.Iterable` of :class:`Subject` or else objects that will
                    be converted to the primary of a `Subject`.
    """
    # TODO(John Sirois): There's no reason this couldn't also just be a function.
    self._task_type = task_type

    self._subjects = frozenset(Subject.as_subject(subject) for subject in subjects)
    self._inputs = inputs

  @property
  def subjects(self):
    """Return the subjects of this plan.

    When the plan is executed, its results will be associated with each one of these subjects.

    :rtype: frozenset of :class:`Subject`
    """
    return self._subjects

  def __getattr__(self, item):
    return self._inputs[item]

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

    return Binding(_execute_binding, args=(self._task_type,), kwargs=inputs)

  def _asdict(self):
    d = self._inputs.copy()
    d.update(task_type=self._task_type, subjects=tuple(self._subjects))
    return d

  def _key(self):
    def hashable(value):
      if self._is_mapping(value):
        return tuple(sorted((k, hashable(v)) for k, v in value.items()))
      elif self._is_iterable(value):
        return tuple(hashable(v) for v in value)
      else:
        return value
    return self._task_type, self._subjects, hashable(self._inputs)

  def __hash__(self):
    return hash(self._key())

  def __eq__(self, other):
    return isinstance(other, Plan) and self._key() == other._key()

  def __ne__(self, other):
    return not (self == other)

  def __repr__(self):
    return ('Plan(task_type={!r}, subjects={!r}, inputs={!r})'
            .format(self._task_type, self._subjects, self._inputs))


class SchedulingError(Exception):
  """Indicates inability to make a required scheduling promise."""


class Scheduler(object):
  """Schedule the creation of products."""

  def promise(self, subject, product_type, required=True):
    """Return an promise for a product of the given `product_type` for the given `subject`.

    If the promise is required and no production plans can be made a
    :class:`Scheduler.SchedulingError` is raised.

    :param subject: The subject that the product type should be created for.
    :param product_type: The type of product to promise production of for the given subject.
    :param bool required: `False` if the product is not required; `True` by default.
    :returns: A promise to make the given product type available for subject at task execution time
              or None if the promise was not required and no production plans could be made.
    :rtype: :class:`Promise`
    :raises: :class:`SchedulerError` if the promise was required and no production plans could be
             made.
    """
    # TODO(John Sirois): Get to the bottom of this when using an AbstractClass base and
    # @abstractmethod:
    #  ERROR collecting tests/python/pants_test/engine/exp/test_scheduler.py
    # tests/python/pants_test/engine/exp/test_scheduler.py:20: in <module>
    #     from pants.engine.exp.scheduler import (BuildRequest, GlobalScheduler, Plan, Planners, Promise,
    #                                             src/python/pants/engine/exp/scheduler.py:418: in <module>
    #     class LocalScheduler(Scheduler):
    #   ../jsirois-pants3/build-support/pants_dev_deps.venv/lib/python2.7/abc.py:90: in __new__
    #   for name, value in namespace.items()
    # ../jsirois-pants3/build-support/pants_dev_deps.venv/lib/python2.7/abc.py:91: in <genexpr>
    # if getattr(value, "__isabstractmethod__", False))
    # src/python/pants/engine/exp/scheduler.py:111: in __getattr__
    # return self._inputs[item]
    # E   KeyError: '__isabstractmethod__'
    raise NotImplementedError()


class TaskPlanner(AbstractClass):
  """Produces plans to control execution of a paired task."""

  class Error(Exception):
    """Indicates an error creating a product plan for a subject."""

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
  def plan(self, scheduler, product_type, subject):
    """
    :param scheduler: A scheduler that can supply promises for any inputs needed that the planner
                      cannot supply on its own to its associated task.
    :type scheduler: :class:`Scheduler`
    :param type product_type: The type of product this plan should produce given subject when
                              executed.
    :param object subject: The subject of the plan.  Any products produced will be for the subject.
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
    for promise in self._root_promises:
      for plan in self._walk_plan(promise, plans):
        yield plan

  def _walk_plan(self, promise, plans):
    plan = self._product_mapper.promised(promise)
    if plan not in plans:
      plans.add(plan)
      for pr in plan.promises:
        for pl in self._walk_plan(pr, plans):
          yield pl
      yield promise._product_type, plan


class Promise(object):
  """Represents a promise to produce a given product type for a given subject."""

  def __init__(self, product_type, subject):
    """
    :param type product_type: The type of product promised.
    :param subject: The subject the product will be produced for; ie: a java library would be a
                    natural subject for a request for classfile products.
    :type subject: :class:`Subject` or else any object that will be the primary of the stored
                   `Subject`.
    """
    self._product_type = product_type
    self._subject = Subject.as_subject(subject)

  @property
  def subject(self):
    """Return the subject of this promise.

    :rtype: :class:`Subject`
    """
    return self._subject

  def _key(self):
    # We promise the product_type for the primary subject, the alternate does not affect consume
    # side identity.
    return self._product_type, self._subject.primary

  def __hash__(self):
    return hash(self._key())

  def __eq__(self, other):
    return isinstance(other, Promise) and self._key() == other._key()

  def __ne__(self, other):
    return not (self == other)

  def __repr__(self):
    return 'Promise(product_type={!r}, subject={!r})'.format(self._product_type, self._subject)


class ProductMapper(object):
  """Stores the mapping from promises to the plans whose execution will satisfy them."""

  class InvalidRegistrationError(Exception):
    """Indicates registration of a plan that does not cover the expected subject."""

  def __init__(self):
    self._promises = {}

  def register_promises(self, product_type, plan, primary_subject=None):
    """Registers the promises the given plan will satisfy when executed.

    :param type product_type: The product type the plan will produce when executed.
    :param plan: The plan to register promises for.
    :type plan: :class:`Plan`
    :param primary_subject: An optional primary subject.  If supplied, the registered promise for
                            this subject will be returned.
    :returns: The promise for the primary subject of one was supplied.
    :rtype: :class:`Promise`
    :raises:
    """
    # Index by all subjects.  This allows dependencies on products from "chunking" tasks, even
    # products from tasks that act globally in the extreme.
    primary_promise = None
    for subject in plan.subjects:
      promise = Promise(product_type, subject)
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
  """A scheduler that formulates an execution graph locally.

  This implementation is synchronous in addition to being local.
  """

  class NoProducersError(SchedulingError):
    """Indicates no planners were able to promise a required product for a given subject."""

    def __init__(self, product_type, subject=None):
      msg = ('No plans to generate {!r}{} could be made.'
             .format(product_type.__name__, ' {!r}'.format(subject) if subject else ''))
      super(LocalScheduler.NoProducersError, self).__init__(msg)

  class ConflictingProducersError(SchedulingError):
    """Indicates more than one planner was able to promise a product for a given subject."""

    def __init__(self, product_type, subject, planners):
      msg = ('Collected the following plans for generating {!r} from {!r}\n\t{}'
             .format(product_type.__name__,
                     subject,
                     '\n\t'.join(type(p).__name__ for p in planners)))
      super(LocalScheduler.ConflictingProducersError, self).__init__(msg)

  def __init__(self, planners):
    """
    :param planners: All the planners installed in the system.
    :type planners: :class:`Planners`
    """
    self._planners = planners
    self._product_mapper = ProductMapper()
    self._plans_by_product_type_by_planner = defaultdict(lambda: defaultdict(OrderedSet))

  def formulate_graph(self, goals, subjects):
    """Formulate the execution graph that satisfies the given `build_request`.

    :param goals: The names of the goals to achieve.
    :type goals: :class:`collections.Iterable` of string
    :param list subjects: The subjects to attempt the given goals for.
    :returns: An execution graph of plans, that when reduced
    :returns: An execution graph of plans that, when reduced, can satisfy the given build request.
    :raises: :class:`LocalScheduler.SchedulingError` if no execution graph solution could be found.
    """
    root_promises = []
    for goal in goals:
      for planner in self._planners.for_goal(goal):
        for product_type in planner.product_types:
          # TODO(John Sirois): Allow for subject-less (target-less) goals.  Examples are clean-all,
          # ng-killall, and buildgen.go.
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
  NO_PLAN = Plan(task_type=None, subjects=())

  def promise(self, subject, product_type, required=True):
    promise = Promise(product_type, subject)
    plan = self._product_mapper.promised(promise)
    if plan is not None:
      # The `NO_PLAN` plan may have been decided in a non-required round.
      if required and promise is self.NO_PLAN:
        raise self.NoProducersError(product_type, subject)
      return None

    planners = self._planners.for_product_type(product_type)
    if required and not planners:
      raise self.NoProducersError(product_type)

    plans = []
    for planner in planners:
      plan = planner.plan(self, product_type, subject)
      if plan:
        plans.append((planner, plan))

    if len(plans) > 1:
      planners = [planner for planner, plan in plans]
      raise self.ConflictingProducersError(product_type, subject, planners)
    elif not plans:
      if required:
        raise self.NoProducersError(product_type, subject)
      self._product_mapper.register_promises(product_type, self.NO_PLAN)
      return None

    planner, plan = plans[0]
    try:
      primary_promise = self._product_mapper.register_promises(product_type, plan,
                                                               primary_subject=subject)
      self._plans_by_product_type_by_planner[planner][product_type].add(plan)
      return primary_promise
    except ProductMapper.InvalidRegistrationError:
      raise SchedulingError('The plan produced for {subject!r} by {planner!r} does not cover '
                            '{subject!r}:\n\t{plan!r}'.format(subject=subject,
                                                              planner=type(planner).__name__,
                                                              plan=plan))


class GlobalScheduler(object):
  """Generates execution graphs for build requests.

  This is the front-end of the new pants execution engine.
  """

  def __init__(self, graph, planners):
    """
    :param graph: The BUILD graph build requests will execute against.
    :type graph: :class:`pants.engine.exp.graph.Graph`
    :param planners: All the task planners known to the system.
    :type planners: :class:`Planners`
    """
    self._graph = graph
    self._planners = planners

  def execution_graph(self, build_request):
    """Create an execution graph that can satisfy the given build request.

    :param build_request: The description of the goals to achieve.
    :type build_request: :class:`BuildRequest`
    :returns: An execution graph of plans that, when reduced, can satisfy the given build request.
    :rtype: :class:`ExecutionGraph`
    """
    scheduler = LocalScheduler(planners=self._planners)
    goals = build_request.goals
    subjects = [self._graph.resolve(a) for a in build_request.addressable_roots]
    return scheduler.formulate_graph(goals, subjects)


class Engine(AbstractClass):
  """An engine for running a pants command line."""

  class Result(collections.namedtuple('Result', ['exit_code', 'root_products'])):
    """Represents the result of a single engine run."""

    @classmethod
    def success(cls, root_products):
      return cls(exit_code=0, root_products=root_products)

    @classmethod
    def failure(cls, exit_code):
      return cls(exit_code=exit_code, root_products=None)

  def __init__(self, global_scheduler):
    """
    :param global_scheduler: The global scheduler for creating execution graphs.
    :type global_scheduler: :class:`GlobalScheduler`
    """
    self._global_scheduler = global_scheduler

  def execute(self, build_request):
    """Executes the the requested build.

    :param build_request: The description of the goals to achieve.
    :type build_request: :class:`BuildRequest`
    :returns: The result of the run.
    :rtype: :class:`Engine.Result`
    """
    execution_graph = self._global_scheduler.execution_graph(build_request)
    try:
      root_products = self.reduce(execution_graph)
      return self.Result.success(root_products)
    except TaskError as e:
      message = str(e)
      if message:
        print('\nFAILURE: {0}\n'.format(message))
      else:
        print('\nFAILURE\n')
      return self.Result.failure(e.exit_code)

  @abstractmethod
  def reduce(self, execution_graph):
    """Reduce the given execution graph returning its root products.

    :param execution_graph: An execution graph of plans to reduce.
    :type execution_graph: :class:`ExecutionGraph`
    :returns: The root products promised by the execution graph.
    :rtype: dict of (:class:`Promise`, product)
    """


class LocalSerialEngine(Engine):
  """An engine that runs tasks locally and serially in-process."""

  def reduce(self, execution_graph):
    # TODO(John Sirois): Robustify products_by_promise indexed accesses and raise helpful exceptions
    # when there is an unexpected missed promise key.

    products_by_promise = {}
    for product_type, plan in execution_graph.walk():
      binding = plan.bind({promise: products_by_promise[promise] for promise in plan.promises})
      product = binding.execute()
      for subject in plan.subjects:
        products_by_promise[Promise(product_type, subject)] = product

    return {root_promise: products_by_promise[root_promise]
            for root_promise in execution_graph.root_promises}


def _execute_plan(func, product_type, subjects, *args, **kwargs):
  # A picklable top-level function to help support local multiprocessing uses.
  product = func(*args, **kwargs)
  return product_type, subjects, product


class LocalMultiprocessEngine(Engine):
  """An engine that runs tasks locally and in parallel when possible using a process pool."""

  def __init__(self, global_scheduler, pool_size=0):
    """
    :param global_scheduler: The global scheduler for creating execution graphs.
    :type global_scheduler: :class:`GlobalScheduler`
    :param pool: A multiprocessing process pool.
    :type pool: :class:`multiprocessing.Pool`
    """
    super(LocalMultiprocessEngine, self).__init__(global_scheduler)
    self._pool_size = pool_size if pool_size > 0 else multiprocessing.cpu_count()
    self._pool = multiprocessing.Pool(self._pool_size)

  class Executor(Thread):
    LAST_PLAN = object()

    def __init__(self, pool, pool_size):
      super(LocalMultiprocessEngine.Executor, self).__init__()

      self._pool = pool
      self._pool_size = pool_size
      self._waiting = []
      self._plans = Queue.Queue(self._pool_size)
      self._results = Queue.Queue()
      self._products_by_promise = {}

      self.name = 'LocalMultiprocessEngine.Executor'
      self.daemon = True
      self.start()

    def enqueue(self, plan):
      self._plans.put(plan)

    def finish(self, promises):
      self._plans.put(self.LAST_PLAN)
      self.join()
      return {promise: self._products_by_promise[promise] for promise in promises}

    def run(self):
      while True:
        done = self._fill_waiting()
        while self._waiting:
          self._submit_all_satisfied()
          self._gather_one()
          if not done:
            break
        if done:
          break

    def _fill_waiting(self):
      while len(self._waiting) < self._pool_size:
        plan = self._plans.get()
        if plan is self.LAST_PLAN:
          return True
        else:
          self._waiting.append(plan)

    def _submit_all_satisfied(self):
      for index, (product_type, plan) in enumerate(self._waiting):
        if all(promise in self._products_by_promise for promise in plan.promises):
          self._waiting.pop(index)
          func, args, kwargs = plan.bind({promise: self._products_by_promise[promise]
                                          for promise in plan.promises})
          execute_plan = functools.partial(_execute_plan, func, product_type, plan.subjects)
          self._pool.apply_async(execute_plan, args=args, kwds=kwargs, callback=self._results.put)

    def _gather_one(self):
      product_type, subjects, product = self._results.get()
      for subject in subjects:
        self._products_by_promise[Promise(product_type, subject)] = product

  def reduce(self, execution_graph):
    executor = self.Executor(self._pool, self._pool_size)
    for plan in execution_graph.walk():
      executor.enqueue(plan)
    return executor.finish(execution_graph.root_promises)

  def close(self):
    self._pool.close()
    self._pool.join()
