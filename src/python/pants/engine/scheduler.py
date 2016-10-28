# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import threading
import time
from collections import deque
from contextlib import contextmanager

from pants.base.specs import (AscendantAddresses, DescendantAddresses, SiblingAddresses,
                              SingleAddress)
from pants.build_graph.address import Address
from pants.engine.addressable import Addresses
from pants.engine.fs import PathGlobs
from pants.engine.nodes import (ConflictingProducersError, DependenciesNode, FilesystemNode, Node,
                                Noop, ProjectionNode, Return, Runnable, SelectNode, State, TaskNode,
                                Throw, Waiting)
from pants.engine.rules import (GraphMaker, NodeBuilder, RootRule, RuleGraphEntry, RuleGraphLiteral,
                                RuleGraphSubjectIsProduct, RuleIndex, RulesetValidator)
from pants.engine.selectors import (Select, SelectDependencies, SelectProjection,
                                    type_or_constraint_repr)
from pants.engine.struct import Variants
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


class CompletedNodeException(ValueError):
  """Indicates an attempt to change a Node that is already completed."""


class IncompleteDependencyException(ValueError):
  """Indicates an attempt to complete a Node that has incomplete dependencies."""


class ProductGraph(object):

  class Entry(object):
    """An entry representing a Node in the ProductGraph.

    Equality for this object is intentionally `identity` for efficiency purposes: structural
    equality can be implemented by comparing the result of the `structure` method.
    """
    __slots__ = ('node', 'rule_edges', 'state', 'dependencies', 'dependents', 'cyclic_dependencies')

    def __init__(self, node, rule_edges):
      self.node = node
      self.rule_edges = rule_edges
      # The computed value for a Node: if a Node hasn't been computed yet, it will be None.
      self.state = None
      # Sets of dependency/dependent Entry objects.
      self.dependencies = set()
      self.dependents = set()
      # Illegal/cyclic dependency Nodes. We prevent cyclic dependencies from being introduced into the
      # dependencies/dependents lists themselves, but track them independently in order to provide
      # context specific error messages when they are introduced.
      self.cyclic_dependencies = set()

    def ready(self):
      # TODO, conceivably, this could check that the node has all of its selectors fulfilled instead of
      readiness = not self.dependencies or all(dep_entry.is_complete for dep_entry in self.dependencies)
      return readiness

    @property
    def is_complete(self):
      return self.state is not None

    def validate_not_complete(self):
      if self.is_complete:
        # It's important not to allow state changes on completed Nodes, because that invariant
        # is used in cycle detection to avoid walking into completed Nodes.
        raise CompletedNodeException('Node {} is already completed with:\n  {}'
                                    .format(self.node, self.state))

    def set_state(self, state):
      self.validate_not_complete()

      # Validate that a completed Node depends only on other completed Nodes.
      for dep in self.dependencies:
        if not dep.is_complete:
          raise IncompleteDependencyException(
              'Cannot complete {} with {} while it has an incomplete dep:\n  {}'
                .format(self, state, dep.node))

      # Finally, set.
      self.state = state

    def structure(self):
      return (self.node,
              self.state,
              {d.node for d in self.dependencies},
              {d.node for d in self.dependents},
              self.cyclic_dependencies)
    #def __repr__(self):
    #  return '{}({})'.format(type(self).__name__, self.node)

  def __init__(self, validator=None, rule_graph=None):
    self._validator = validator or Node.validate_node
    # A dict of Node->Entry.
    self._nodes = dict()
    self._rule_graph = rule_graph

  def __len__(self):
    return len(self._nodes)

  def is_complete(self, node):
    entry = self._nodes.get(node, None)
    return entry and entry.is_complete

  def state(self, node):
    entry = self._nodes.get(node, None)
    if not entry:
      return None
    return entry.state

  def complete_node(self, node, state):
    """Updates the Node with the given State, creating any Nodes which do not already exist."""
    if type(state) not in (Return, Throw, Noop):
      raise ValueError('A Node may only be completed with a final State. Got: {}'.format(state))
    entry = self.ensure_entry(node)
    entry.set_state(state)

  def add_dependencies(self, node, dependencies):
    #assert node in self._nodes
    entry = self.ensure_entry(node)
    entry.validate_not_complete()
    self._add_dependencies(entry, dependencies)

  def _detect_cycle(self, src, dest):
    """Detect whether adding an edge from src to dest would create a cycle.

    :param src: Source entry: must exist in the graph.
    :param dest: Destination entry: must exist in the graph.

    Returns True if a cycle would be created by adding an edge from src->dest.
    """
    # We disallow adding new edges outbound from completed Nodes, and no completed Node can have
    # a path to an uncompleted Node. Thus, we can truncate our search for cycles at any completed
    # Node.
    is_not_completed = lambda e: e.state is None
    for entry in self._walk_entries([dest], entry_predicate=is_not_completed):
      if entry is src:
        return True
    return False

  def ensure_entry(self, node):
    """Returns the Entry for the given Node, creating it if it does not already exist.

    If it can be predetermined that the node will fail, fail it.
    """
    entry = self._nodes.get(node, None)
    if not entry:
      #raise Exception("ensure entry called without entry existing {}".format(node))
      self._validator(node)
      edges = RuleGraphEdgeContainer(node, self._rule_graph)
      self._nodes[node] = entry = self.Entry(node, edges)

      if edges.will_noop:
        self.complete_node(node, edges.noop_reason)

    return entry

  def ensure_entry_and_expand(self, node):
    entry = self._nodes.get(node, None)
    if not entry:
      self._validator(node)

      # perhaps, the edges should be added once the known deps are in the build graph?
      edges = RuleGraphEdgeContainer(node, self._rule_graph)
      self._nodes[node] = entry = self.Entry(node, edges)

      if edges.will_noop:
        self.complete_node(node, edges.noop_reason)
        return set()
      else:
        next_set = self.fill_in_discoverable_deps(entry)
        if next_set:
          return next_set
    return {entry}

  def fill_in_discoverable_deps(self, entry):
    expanded_entries = {entry}

    rule_edges = entry.rule_edges
    if rule_edges.current_node_is_rule_holder:

      entry.validate_not_complete()

      for selector in rule_edges._current_node.rule.input_selectors:

        selector_path = rule_edges._initial_selector_path(selector)
        state_for_selector = rule_edges.get_state_for_selector(
          selector_path,
          rule_edges._current_node.subject, # TODO resolve the _s here
          rule_edges._current_node.variants,
          # We always return the default here because we want to be sure if there's a node it bubbles
          # up as a waiting state entry
          # hm. another possibility would be to do the actual check against state, and mark the node
          # completed if all of its deps exist -- can't because it hasn't run yet. :/
          lambda n, default: default,
          on_no_matches_wait=True
        )
        if type(state_for_selector) is Waiting:
          expanded_entries.update(self._add_dependencies(entry, state_for_selector.dependencies))
        elif type(state_for_selector) is Return:
          pass
        else:
          raise Exception("expected state to be waiting {}".format(state_for_selector))

    return {e for e in expanded_entries if not e.is_complete and e.ready()}

  def _add_dependencies(self, node_entry, dependencies):
    """Adds dependency edges from the given src Node to the given dependency Nodes.

    Executes cycle detection: if adding one of the given dependencies would create
    a cycle, then the _source_ Node is marked as a Noop with an error indicating the
    cycle path, and the dependencies are not introduced.
    """

    # Add deps. Any deps which would cause a cycle are added to cyclic_dependencies instead,
    # and ignored except for the purposes of Step execution.
    ret = set()
    for dependency in dependencies:
      alls = self.ensure_entry_and_expand(dependency)
      dependency_entry = self.ensure_entry(dependency)
      if dependency_entry in node_entry.dependencies:
        #logger.debug('in deps {}'.format(dependency_entry))
        continue
      if dependency_entry.rule_edges.will_noop:
        #logger.debug('dep is statically determined noop')
        continue
      if self._detect_cycle(node_entry, dependency_entry):
        #logger.debug('cycle detected! src: {} dep: {}'.format(node_entry, dependency_entry))
        node_entry.cyclic_dependencies.add(dependency)
      else:
        #logger.debug('adding dependency {}'.format(dependency_entry))
        if dependency_entry.node in node_entry.cyclic_dependencies:
          raise Exception("was already a cyclic dependency!")

        node_entry.dependencies.add(dependency_entry)
        dependency_entry.dependents.add(node_entry)
      ret.update(alls)
    return ret

  def completed_nodes(self):
    """In linear time, yields the states of any Nodes which have completed."""
    for node, entry in self._nodes.items():
      if entry.state is not None:
        yield node, entry.state

  def dependents(self):
    """In linear time, yields the dependents lists for all Nodes."""
    for node, entry in self._nodes.items():
      yield node, [d.node for d in entry.dependents]

  def dependencies(self):
    """In linear time, yields the dependencies lists for all Nodes."""
    for node, entry in self._nodes.items():
      yield node, [d.node for d in entry.dependencies]

  def cyclic_dependencies(self):
    """In linear time, yields the cyclic_dependencies lists for all Nodes."""
    for node, entry in self._nodes.items():
      yield node, entry.cyclic_dependencies

  def dependents_of(self, node):
    entry = self._nodes.get(node, None)
    if entry:
      for d in entry.dependents:
        yield d.node

  def _dependency_entries_of(self, node):
    entry = self._nodes.get(node, None)
    if entry:
      for d in entry.dependencies:
        yield d

  def dependencies_of(self, node):
    for d in self._dependency_entries_of(node):
      yield d.node

  def cyclic_dependencies_of(self, node):
    entry = self._nodes.get(node, None)
    if not entry:
      return set()
    return entry.cyclic_dependencies

  def invalidate(self, predicate=None):
    """Invalidate nodes and their subgraph of dependents given a predicate.

    :param func predicate: A predicate that matches Node objects for all nodes in the graph.
    """
    def _sever_dependents(entry):
      for associated_entry in entry.dependencies:
        associated_entry.dependents.discard(entry)

    def _delete_node(entry):
      actual_entry = self._nodes.pop(entry.node)
      assert entry is actual_entry

    def all_predicate(node, state): return True
    predicate = predicate or all_predicate

    invalidated_root_entries = list(entry for entry in self._nodes.values()
                                    if predicate(entry.node, entry.state))
    invalidated_entries = list(entry for entry in self._walk_entries(invalidated_root_entries,
                                                                     lambda _: True,
                                                                     dependents=True))

    # Sever dependee->dependent relationships in the graph for all given invalidated nodes.
    for entry in invalidated_entries:
      _sever_dependents(entry)

    # Delete all nodes based on a backwards walk of the graph from all matching invalidated roots.
    for entry in invalidated_entries:
      _delete_node(entry)

    invalidated_count = len(invalidated_entries)
    logger.info('invalidated {} of {} nodes'.format(invalidated_count, len(self)))
    return invalidated_count

  def invalidate_files(self, filenames):
    """Given a set of changed filenames, invalidate all related FilesystemNodes in the graph."""
    subjects = set(FilesystemNode.generate_subjects(filenames))
    logger.debug('generated invalidation subjects: %s', subjects)

    def predicate(node, state):
      return type(node) is FilesystemNode and node.subject in subjects

    return self.invalidate(predicate)

  def walk(self, roots, predicate=None, dependents=False):
    """Yields Nodes and their States depth-first in pre-order, starting from the given roots.

    Each node entry is a tuple of (Node, State).

    The given predicate is applied to entries, and eliminates the subgraphs represented by nodes
    that don't match it. The default predicate eliminates all `Noop` subgraphs.
    """
    def _default_entry_predicate(entry):
      return type(entry.state) is not Noop
    def _entry_predicate(entry):
      return predicate(entry.node, entry.state)
    entry_predicate = _entry_predicate if predicate else _default_entry_predicate

    root_entries = []
    for root in roots:
      entry = self._nodes.get(root, None)
      if entry:
        root_entries.append(entry)

    for entry in self._walk_entries(root_entries, entry_predicate, dependents=dependents):
      yield (entry.node, entry.state)

  def _walk_entries(self, root_entries, entry_predicate, dependents=False):
    stack = deque(root_entries)
    walked = set()
    while stack:
      entry = stack.pop()
      if entry in walked:
        continue
      walked.add(entry)
      if not entry_predicate(entry):
        continue
      stack.extend(entry.dependents if dependents else entry.dependencies)

      yield entry

  def trace(self, root):
    """Yields a stringified 'stacktrace' starting from the given failed root.

    TODO: This could use polish. In particular, the `__str__` representations of Nodes and
    States are probably not sufficient for user output.
    """

    traced = set()

    def is_bottom(entry):
      return type(entry.state) in (Noop, Return) or entry in traced

    def is_one_level_above_bottom(parent_entry):
      return all(is_bottom(child_entry) for child_entry in parent_entry.dependencies)

    def _format(level, entry, state):
      output = '{}Computing {} for {} with {} : {}\n{}{}\n{}{}'.format('  ' * level,
                                              type_or_constraint_repr(entry.node.product),
                                              entry.node.subject,
                                              entry.node.rule,
                                              type(entry.node.subject).__name__,
                                                                 '  ' * (level+1),
                                                                 entry,
                                                                       '',''
                                                                 )
      #if is_one_level_above_bottom(entry):
      output += '\n{}state: {}'.format('  ' * (level + 1), state)

      return output

    def _trace(entry, level):
      if is_bottom(entry):
        yield '{}bottomed'.format('  '*level)
        #return
      traced.add(entry)
      yield _format(level, entry, entry.state)
      if entry.cyclic_dependencies:
        yield '{}^^ has cycles'.format('  '*level)
      for dep in entry.cyclic_dependencies:
        yield _format(level, entry, Noop.cycle(entry.node, dep))
      if entry.dependencies:
        yield '{}^^ has deps'.format('  '*level)
      for dep_entry in entry.dependencies:
        for l in _trace(dep_entry, level+1):
          yield l

    for line in _trace(self._nodes[root], 1):
      yield line

  def visualize(self, roots):
    """Visualize a graph walk by generating graphviz `dot` output.

    :param iterable roots: An iterable of the root nodes to begin the graph walk from.
    """
    viz_colors = {}
    viz_color_scheme = 'set312'  # NB: There are only 12 colors in `set312`.
    viz_max_colors = 12

    def format_color(node, node_state):
      if type(node_state) is Throw:
        return 'tomato'
      elif type(node_state) is Noop:
        return 'white'
      return viz_colors.setdefault(node.product, (len(viz_colors) % viz_max_colors) + 1)

    def format_type(node):
      return node.func.__name__ if type(node) is TaskNode else type(node).__name__

    def format_subject(node):
      if node.variants:
        return '({})@{}'.format(node.subject,
                                ','.join('{}={}'.format(k, v) for k, v in node.variants))
      else:
        return '({})'.format(node.subject)

    def format_product(node):
      if type(node) is SelectNode and node.variant_key:
        return '{}@{}'.format(node.product.__name__, node.variant_key)
      return node.product.__name__

    def format_node(node, state):
      return '{}:{}:{} == {}'.format(format_product(node),
                                     format_subject(node),
                                     format_type(node),
                                     str(state).replace('"', '\\"'))

    def format_edge(src_str, dest_str, cyclic):
      style = " [style=dashed]" if cyclic else ""
      return '    "{}" -> "{}"{}'.format(node_str, format_node(dep, dep_state), style)

    yield 'digraph plans {'
    yield '  node[colorscheme={}];'.format(viz_color_scheme)
    yield '  concentrate=true;'
    yield '  rankdir=LR;'

    predicate = lambda n, s: type(s) is not Noop

    for (node, node_state) in self.walk(roots, predicate=predicate):
      node_str = format_node(node, node_state)

      yield '  "{}" [style=filled, fillcolor={}];'.format(node_str, format_color(node, node_state))

      for cyclic, adjacencies in ((False, self.dependencies_of), (True, self.cyclic_dependencies_of)):
        for dep in adjacencies(node):
          dep_state = self.state(dep)
          if not predicate(dep, dep_state):
            continue
          yield format_edge(node_str, format_node(dep, dep_state), cyclic)

    yield '}'


def try_id(i):
  return i


class ExecutionRequest(datatype('ExecutionRequest', ['roots'])):
  """Holds the roots for an execution, which might have been requested by a user.

  To create an ExecutionRequest, see `LocalScheduler.build_request` (which performs goal
  translation) or `LocalScheduler.execution_request`.

  :param roots: Root Nodes for this request.
  :type roots: list of :class:`pants.engine.nodes.Node`
  """


class LocalScheduler(object):
  """A scheduler that expands a ProductGraph by executing user defined tasks."""

  def __init__(self,
               goals,
               tasks,
               project_tree,
               graph_lock=None,
               inline_nodes=True,
               graph_validator=None):
    """
    :param goals: A dict from a goal name to a product type. A goal is just an alias for a
           particular (possibly synthetic) product.
    :param tasks: A set of (output, input selection clause, task function) triples which
           is used to compute values in the product graph.
    :param project_tree: An instance of ProjectTree for the current build root.
    :param graph_lock: A re-entrant lock to use for guarding access to the internal ProductGraph
                       instance. Defaults to creating a new threading.RLock().
    :param inline_nodes: Whether to inline execution of `inlineable` Nodes. This improves
                         performance, but can make debugging more difficult because the entire
                         execution history is not recorded in the ProductGraph.
    :param graph_validator: A validator that runs over the entire graph after every scheduling
                            attempt. Very expensive, very experimental.
    """

    select_product = lambda product: Select(product)
    select_dep_addrs = lambda product: SelectDependencies(product, Addresses, field_types=(Address,))
    self._root_selector_fns = {
      Address: select_product,
      PathGlobs: select_product,
      SingleAddress: select_dep_addrs,
      SiblingAddresses: select_dep_addrs,
      AscendantAddresses: select_dep_addrs,
      DescendantAddresses: select_dep_addrs,
    }

    self._rule_index = RuleIndex.create(tasks)
    self._node_builder = NodeBuilder(self._rule_index)

    self._rule_graph = GraphMaker(self._rule_index, self._root_selector_fns).full_graph()
    RulesetValidator(self._rule_graph, goals).validate()

    self._products_by_goal = goals
    self._project_tree = project_tree

    self._graph_validator = graph_validator
    self._product_graph = ProductGraph(rule_graph=self._rule_graph)
    self._product_graph_lock = graph_lock or threading.RLock()
    self._inline_nodes = inline_nodes

  def visualize_graph_to_file(self, roots, filename):
    """Visualize a graph walk by writing graphviz `dot` output to a file.

    :param iterable roots: An iterable of the root nodes to begin the graph walk from.
    :param str filename: The filename to output the graphviz output to.
    """
    with self._product_graph_lock, open(filename, 'wb') as fh:
      for line in self.product_graph.visualize(roots):
        fh.write(line)
        fh.write('\n')

  def _attempt_run_step(self, node_entry):
    """Attempt to run a Step with the currently available dependencies of the given Node.

    If the currently declared dependencies of a Node are not yet available, returns None. If
    they are available, runs a Step and returns the resulting State.
    """
    # See whether all of the dependencies for the node are available.
    if not node_entry.ready():
      return None

    # Collect the deps.
    deps = dict()
    for dep_entry in node_entry.dependencies:
      deps[dep_entry.node] = dep_entry.state
    # Additionally, include Noops for any dependencies that were cyclic.
    for dep in node_entry.cyclic_dependencies:
      #logger.debug('adding cycles to dep state')
      deps[dep] = Noop.cycle(node_entry.node, dep)

    # Run.
    step_context = StepContext(node_entry.rule_edges, self._project_tree, deps)
    step = node_entry.node.step(step_context)
    #logger.debug('-- step result -- {}'.format(step))
    return step

  @property
  def node_builder(self):
    """Return the NodeBuilder instance for this Scheduler.

    A NodeBuilder is a relatively heavyweight object (since it contains an index of all
    registered tasks), so it should be used for the execution of multiple Steps.
    """
    return self._node_builder

  def build_request(self, goals, subjects):
    """Translate the given goal names into product types, and return an ExecutionRequest.

    :param goals: The list of goal names supplied on the command line.
    :type goals: list of string
    :param subjects: A list of Spec and/or PathGlobs objects.
    :type subject: list of :class:`pants.base.specs.Spec`, `pants.build_graph.Address`, and/or
      :class:`pants.engine.fs.PathGlobs` objects.
    :returns: An ExecutionRequest for the given goals and subjects.
    """
    return self.execution_request([self._products_by_goal[goal_name] for goal_name in goals],
                                  subjects)

  def execution_request(self, products, subjects):
    """Create and return an ExecutionRequest for the given products and subjects.

    The resulting ExecutionRequest object will contain keys tied to this scheduler's ProductGraph, and
    so it will not be directly usable with other scheduler instances without being re-created.

    An ExecutionRequest for an Address represents exactly one product output, as does SingleAddress. But
    we differentiate between them here in order to normalize the output for all Spec objects
    as "list of product".

    :param products: A list of product types to request for the roots.
    :type products: list of types
    :param subjects: A list of Spec and/or PathGlobs objects.
    :type subject: list of :class:`pants.base.specs.Spec`, `pants.build_graph.Address`, and/or
      :class:`pants.engine.fs.PathGlobs` objects.
    :returns: An ExecutionRequest for the given products and subjects.
    """
    # we have a collection of subject, product_type tuples
    # so, let's boil that down to subject_type, product_type tuples.
    # then
    #

    # bits that are important
    # brute force
    # (subject, product_type) -> root rules that fulfill that tuple.
    # some tuples will have no root rules
    # if the root rule has only one dep, turn it into a node
    # otherwise we need to do pick first on node version


    def selector_subjects():
      for subject in subjects:
        selector_fn = self._root_selector_fns.get(type(subject), None)
        if not selector_fn:
          raise TypeError('Unsupported root subject type: {} for {!r}'
                          .format(type(subject), subject))

        for product in products:
          yield selector_fn(product), subject

    return self.selection_request(list(selector_subjects()))

  def selection_request(self, requests):
    """Create and return an ExecutionRequest for the given (selector, subject) tuples.

    This method allows users to specify their own selectors. It has the potential to replace
    execution_request, which is a subset of this method, because it uses default selectors.
    :param requests: A list of (selector, subject) tuples.
    :return: An ExecutionRequest for the given selectors and subjects.
    """
    #TODO: Think about how to deprecate the existing execution_request API.

    def rule_subject():
      for selector, subject in requests:
        matching_root_graph_entry = self._rule_graph.root_rule_matching(type(subject), selector)
        if not matching_root_graph_entry:
          #raise Exception("What is all this then. No matching for {} {}".format(subject, selector))
          # TODO the message here should say how to avoid this. So that goals can move towards static
          # definition
          logger.debug("What is all this then. No matching for {} {}".format(selector, subject))
          logger.debug("rule table {} {}:\n  {}".format(type(subject).__name__, selector.product,'\n  '.join(str(n) for n in self._rule_graph.root_rules.keys() if type(subject) is n.subject_type and n.selector.product is selector.product)))
          logger.debug("rule table:\n  {}".format('\n  '.join(str(n) for n in self._rule_graph.root_rules.keys() if type(subject) is n.subject_type)))

          # TODO this updating bit is less than ideal.
          self._rule_graph = self._rule_graph.new_graph_with_root_for(type(subject), selector)
          self._product_graph._rule_graph = self._rule_graph
          RulesetValidator(self._rule_graph, self._products_by_goal).validate()

          matching_root_graph_entry = self._rule_graph.root_rule_matching(type(subject), selector)
          if not matching_root_graph_entry:
            logger.debug('still no matching entry after updating rule graph!')
            continue
          # Try updating the rule graph to include the rule, or alternatively we could yield the cases that failed and collect them
        yield (matching_root_graph_entry, subject)

    root_nodes = set(RootRule(type(subject), root.selector).as_node(subject, None)
                     for root, subject in rule_subject())

    return ExecutionRequest(root_nodes)

  @property
  def product_graph(self):
    return self._product_graph

  @contextmanager
  def locked(self):
    with self._product_graph_lock:
      yield

  def root_entries(self, execution_request):
    """Returns the roots for the given ExecutionRequest as a dict from Node to State."""
    with self._product_graph_lock:
      return {root: self._product_graph.state(root) for root in execution_request.roots}

  def invalidate_files(self, filenames):
    """Calls `ProductGraph.invalidate_files()` against an internal ProductGraph instance
    under protection of a scheduler-level lock."""
    with self._product_graph_lock:
      return self._product_graph.invalidate_files(filenames)

  def schedule(self, execution_request):
    """Yields batches of Steps until the roots specified by the request have been completed.

    This method should be called by exactly one scheduling thread, but the Step objects returned
    by this method are intended to be executed in multiple threads, and then satisfied by the
    scheduling thread.
    """
    with self._product_graph_lock:
      # A dict from Node entry to a possibly executing Step. Only one Step exists for a Node at a time.
      outstanding = set()
      # Node entries that might need to have Steps created (after any outstanding Step returns).
      #logger.debug('before expanding roots')
      expanded_roots = set()
      for root_node in execution_request.roots:
        expanded_roots.update(self._product_graph.ensure_entry_and_expand(root_node))
      #logger.debug('after expanding roots')

      candidates = deque(expanded_roots)

      # Yield nodes that are Runnable, and then compute new ones.
      step_count, runnable_count, scheduling_iterations = 0, 0, 0
      start_time = time.time()
      yield_time = 0
      while True:
        # Drain the candidate list to create Runnables for the Engine.
        runnable = []
        while candidates:
          node_entry = candidates.popleft()
          if node_entry.is_complete or node_entry in outstanding:
            # Node has already completed, or is runnable
            continue
          # Create a step if all dependencies are available; otherwise, can assume they are
          # outstanding, and will cause this Node to become a candidate again later.
          state = self._attempt_run_step(node_entry)
          if state is None:
            # No state change.
            continue

          # The Node's state is changing due to this Step.
          step_count += 1
          if type(state) is Runnable:
            # The Node is ready to run in the Engine.
            runnable.append((node_entry, state))
            outstanding.add(node_entry)
          elif type(state) is Waiting:
            incomplete_deps = set()
            for n in state.dependencies:
              discoverable_deps = self._product_graph.ensure_entry_and_expand(n)
              incomplete_deps.update(d for d in discoverable_deps
                                     if not d.is_complete and
                                        d is not node_entry.node)

              # Waiting on dependencies.
            self._product_graph.add_dependencies(node_entry.node, state.dependencies)
            incomplete_deps.update(d for d in node_entry.dependencies if not d.is_complete)

            # remove incomplete deps that are noops due to cycles
            incomplete_deps_minus_cyclic_deps = {d for d in incomplete_deps if d.node not in node_entry.cyclic_dependencies}
            if len(incomplete_deps_minus_cyclic_deps) != len(incomplete_deps):
              logger.debug('          ------- removed n {} !'.format(len(incomplete_deps) - len(incomplete_deps_minus_cyclic_deps)))
            incomplete_deps = incomplete_deps_minus_cyclic_deps
            #logger.debug('--- incomplete deps {}'.format(incomplete_deps))
            if incomplete_deps:
              # Mark incomplete deps as candidates for Steps.
              candidates.extend(incomplete_deps)
            else:
              # All deps are already completed: mark this Node as a candidate for another step.
              candidates.append(node_entry)
          else:
            # The Node has completed statically.
            self._product_graph.complete_node(node_entry.node, state)
            candidates.extend(d for d in node_entry.dependents)

        if not runnable and not outstanding:
          # Finished.
          break
        # The double yield here is intentional, and assumes consumption of this generator in
        # a `for` loop with a `generator.send(completed)` call in the body of the loop.
        yield_start_time = time.time()
        completed = yield runnable
        yield
        yield_time += time.time() - yield_start_time
        runnable_count += len(runnable)
        scheduling_iterations += 1

        # Finalize any Runnables that completed in the previous round.
        for node_entry, state in completed:
          # Complete the Node and mark any of its dependents as candidates for Steps.
          outstanding.discard(node_entry)
          self._product_graph.complete_node(node_entry.node, state)
          candidates.extend(d for d in node_entry.dependents)

      total_time = time.time() - start_time
      logger.debug(
        'ran %s scheduling iterations, %s runnables, and %s steps in %f seconds (~%f in scheduler). '
        'there are %s total nodes.',
        scheduling_iterations,
        runnable_count,
        step_count,
        total_time,
        total_time - yield_time,
        len(self._product_graph)
      )

      if self._graph_validator is not None:
        self._graph_validator.validate(self._product_graph)


class RuleGraphEdgeContainer(object):
  def __init__(self, current_node, graph):
    self._current_node = current_node
    self.current_node_is_rule_holder = hasattr(self._current_node, 'rule')

    self.will_noop = False
    self.noop_reason = None

    self._rule_edges = None

    if hasattr(current_node, 'rule') and hasattr(current_node, 'subject'):
      edges = graph.dependency_edges_for_rule(current_node.rule, type(current_node.subject))
      if edges:
        self._rule_edges = edges

        # let's just precompute all of the nodes initial nodes, so we can reuse them later.
        self._selector_to_state_node_tuple = dict()
        for selector in current_node.rule.input_selectors:
          selector_path = self._initial_selector_path(selector)

          nodes, state, rule_deps = self._state_or_nodes_for(selector_path, current_node.subject, current_node.variants)
          if (not nodes and not state) and type(selector_path) is Select:
            raise Exception("didnt get nodes for {}".format(selector_path))
          self._selector_to_state_node_tuple[selector_path] = (nodes, state, rule_deps)
      else:
        self._blow_up_on_missing_edges(graph, current_node)
    else:
      pass

  def get_state_for_selector(self, selector_path, subject, variants, get_state, on_no_matches_wait=False):
    if not self._rule_edges:
      raise Exception("Expected there to be rule edges!")
    nodes, rule_entries_for_debugging, state = self._check_initial_nodes(selector_path)
    if state:
      return state
    if nodes:
      #print('found node: {}'.format(nodes))
      return self._make_state(rule_entries_for_debugging, nodes, get_state, selector_path, variants, on_no_matches_wait=on_no_matches_wait)
    return self._fall_back_to_looking_up_state(selector_path, subject, variants, get_state)

  def _initial_selector_path(self, selector):
    if type(selector) in (SelectDependencies, SelectProjection):
      selector_path = (selector, selector.input_product_selector)
    else:
      selector_path = selector
    return selector_path

  def _blow_up_on_missing_edges(self, graph, current_node):
    logger.debug('couldnt find edges for {}'.format(current_node.rule))
    unfillable = graph.is_unfulfillable(current_node.rule, current_node.subject)
    if unfillable:
      self.will_noop = True
      self.noop_reason = Noop('appears to not be reachable according to the rule graph and unfulfillable state {} ', unfillable)
    else:
      logger.debug('not unfulfillable. :/ {}'.format(current_node))
      logger.debug('   {}'.format(current_node.extra_repr))

      for e in graph.rule_dependencies:
        if e.rule == current_node.rule and e.subject_type == type(current_node.subject):
          logger.debug(' has matching rule / subject pair, but type is {}  {}'.format(type(e), e))
        elif e.rule == current_node.rule:
          logger.debug('rule match, but not subj {} match, {}'.format(type(current_node.subject), e))
      raise Exception("ahhh!")

  def _check_initial_nodes(self, selector_path):
    nodes, state, rule_entries_for_debugging = self._selector_to_state_node_tuple.get(selector_path,
      (tuple(), None, None))
    return nodes, rule_entries_for_debugging, state

  def _fall_back_to_looking_up_state(self, selector_path, subject, variants, get_state):
    if type(selector_path) is SelectDependencies:
      return self._handle_select_deps(get_state, selector_path, subject, variants)
    elif type(selector_path) is SelectProjection:
      return self._handle_select_projection(get_state, selector_path, subject, variants)
    elif type(selector_path) is tuple and selector_path[-1] == Select(Variants):
      raise Exception('got here')
      return Noop('no variant support')
    else:
      return self._state_via_edges(selector_path, subject, variants, get_state)

  def _handle_select_deps(self, get_state, selector_path, subject, variants):
    input_state = self._input_state_for_projecting(get_state, selector_path, subject, variants)

    if type(input_state) in (Throw, Waiting):
      return input_state
    elif type(input_state) is Noop:
      return Noop('Could not compute {} to determine dependencies.', selector_path.input_product_selector)
    elif type(input_state) is not Return:
      State.raise_unrecognized(input_state)

    dependencies = []
    dep_values = []

    # could do something like,
    # if any of the deps are waiting, we know they all will be, so return the nodes for all of them w/o fanfare

    subject_variants = list(DependenciesNode.dependency_subject_variants(selector_path,
                                                                    input_state.value, variants))
    for dep_subject, dep_variants in subject_variants:
      if type(dep_subject) not in selector_path.field_types:
        return Throw(TypeError('Unexpected type "{}" for {}: {!r}'
                               .format(type(dep_subject), selector_path, dep_subject)))


    for dep_subject, dep_variants in subject_variants:
      nodes, state, rule_entries_for_debugging = self._state_or_nodes_for((selector_path, selector_path.projected_product_selector), dep_subject, dep_variants)
      if state:
        continue
      if nodes:
        s = get_state(nodes[0], None)
        if s is None or type(s) is Waiting:
          dependencies.extend(nodes)
    if dependencies:
      return Waiting(dependencies)

    for dep_subject, dep_variants in subject_variants:
      dep_dep_state = self._blah(dep_subject, dep_variants, get_state, selector_path)

      if type(dep_dep_state) is Waiting:
        dependencies.extend(dep_dep_state.dependencies)
      elif type(dep_dep_state) is Return:
        dep_values.append(dep_dep_state.value)
      elif type(dep_dep_state) is Noop:
        return Throw(ValueError('No source of explicit dependency {} for {}'
                                .format(selector_path.projected_product_selector, dep_subject)))
      elif type(dep_dep_state) is Throw:
        # TODO maybe collate these instead of just returning the first one.
        return dep_dep_state
      else:
        State.raise_unrecognized(dep_dep_state)
    if dependencies:
      return Waiting(dependencies)
    return Return(dep_values)

  def _blah(self, dep_subject, dep_variants, get_state, selector_path):
    nodes, state, rule_entries_for_debugging = self._state_or_nodes_for((selector_path, selector_path.projected_product_selector), dep_subject, dep_variants)

    if state:
      return state
    if nodes:
      return self._make_state(rule_entries_for_debugging, nodes, get_state, selector_path, dep_variants)
#
#    dep_dep_state = self._state_via_edges((selector_path, selector_path.projected_product_selector),
#      dep_subject, dep_variants, get_state)
#    return dep_dep_state

  def _handle_select_projection(self, get_state, selector_path, subject, variants):
    input_state = self._input_state_for_projecting(get_state, selector_path, subject, variants)

    if type(input_state) in (Throw, Waiting):
      return input_state
    elif type(input_state) is Noop:
      return Noop('Could not compute {} in order to project its fields.', selector_path.input_product_selector)
    elif type(input_state) is not Return:
      State.raise_unrecognized(input_state)

    try:
      projected_subject = ProjectionNode.construct_projected_subject(selector_path, input_state)
    except Exception as e:
      return Throw(ValueError(
        'Fields {} of {} could not be projected as {}: {}'.format(selector_path.fields, input_state.value,
          selector_path.projected_subject, e)))

    # it would be good to hold on to the result ^^ somehow.

    output_state = self._state_via_edges((selector_path, selector_path.projected_product_selector),
      projected_subject, variants, get_state)

    if type(output_state) in (Return, Throw, Waiting):
      return output_state
    elif type(output_state) is Noop:
      return Throw(ValueError('No source of projected dependency {}'.format(selector_path.projected_product_selector)))
    else:
      State.raise_unrecognized(output_state)

  def _input_state_for_projecting(self, get_state, selector_path, subject, variants):
    initial_path = self._initial_selector_path(selector_path)
    initial_nodes, rule_entries_for_debugging, initial_state = self._check_initial_nodes(initial_path)
    if initial_state:
      dep_state = initial_state
    elif initial_nodes:
      #assert len(initial_nodes) == 1
      dep_state = self._make_state(rule_entries_for_debugging, initial_nodes, get_state,
        initial_path, variants)
    else:
      dep_state = self._state_via_edges(initial_path, subject, variants, get_state)
    return dep_state

  def _state_via_edges(self, selector_path, subject, variants, get_state):
    nodes, state, rule_entries_for_debugging = self._state_or_nodes_for(selector_path, subject, variants)
    if state:
      return state
    if nodes:
      return self._make_state(rule_entries_for_debugging, nodes, get_state, selector_path, variants)
    return Noop('no nodes for {} {} {}. Found rule entries {}', selector_path, subject, variants, rule_entries_for_debugging)
#    raise Exception("Wut {} {} {}".format(selector_path, rule_entries_for_debugging, self._rule_edges._selector_to_deps))

  def _state_or_nodes_for(self, selector_path, subject, variants):
    """Finds states or nodes for the selector path, based on looking at the edges from the currently relevant rule.

    Ignores graph state."""
    rule_entries = list(self._rule_edges.rules_for(selector_path, type(subject)))
    if not rule_entries:
      return None, None, None

    nodes = []
    for rule_entry in rule_entries:
      if type(rule_entry) is RuleGraphSubjectIsProduct:
        assert rule_entry.value == type(subject)
        assert len(rule_entries) == 1, "if subject is product, it should be the only one"
        return None, Return(subject), None
      elif type(rule_entry) is RuleGraphLiteral:
        assert len(rule_entries) == 1, "if literal, it should be the only one"
        return None, Return(rule_entry.value), None
      elif type(rule_entry) is RuleGraphEntry:
        node = rule_entry.rule.as_node(subject, variants)
        nodes.append(node)
      else:
        raise Exception("Unexpected entry type: {}".format(rule_entry))

    if not nodes:
      raise Exception('rule entries yes, but no nodes for those entries {}'.format(rule_entries))
    else:
      return nodes, None, rule_entries

  def _make_state(self, rule_entries, nodes, get_state, selector_path, variants, on_no_matches_wait=False):
    subject = self._current_node.subject
    final_selector = selector_path if type(selector_path) is not tuple else selector_path[-1]
    had_return = None
    state = None
    waiting = []
    matches = []
    for node in nodes:
      state = get_state(node, None)
      if state is None:
        waiting.append(node)
      elif type(state) is Waiting:
        waiting.extend(state.dependencies)
      elif type(state) is Throw:
        return state # always bubble up the first throw
      elif type(state) is Return:
        matched = SelectNode.do_real_select_literal(final_selector.type_constraint, state.value, variants)
        if matched:
          matches.append((node, matched))
      elif type(state) is Noop:
        continue
      else:
        State.raise_unrecognized(state)

    if waiting:
      return Waiting(waiting)
    elif len(matches) == 0:
      if on_no_matches_wait:
        raise Exception('wut')
        # in prep, we should return waiting for this case
        logger.debug('select path {}'.format(selector_path))
        return Waiting(nodes)
      return Noop('No source of {} for {} : {} because no nodes with returns, but there were rule entries {}\n the return if there was one {}\n last state {}', selector_path, type(subject).__name__, subject, rule_entries, had_return, state)
    elif len(matches) > 1:
      # TODO: Multiple successful tasks are not currently supported. We should allow for this
      # by adding support for "mergeable" products. see:
      #   https://github.com/pantsbuild/pants/issues/2526
      return Throw(ConflictingProducersError.create(subject, final_selector.product, matches))
    elif len(matches) == 1:
      return Return(matches[0][1])
    else:
      raise Exception('how? {}'.format(self._current_node))
      pass # what does this mean?


class StepContext(object):
  """Encapsulates external state and the details of creating Nodes.

  This avoids giving Nodes direct access to the task list or subject set.
  """

  def __init__(self, rule_edges, project_tree, node_states):
    """
    :type graph: RuleGraph
    """
    self.project_tree = project_tree
    self._node_states = dict(node_states)

    self.snapshot_archive_root = os.path.join(project_tree.build_root, '.snapshots')
    self._rule_edges = rule_edges

  def select_for(self, selector, subject, variants):
    """Returns the state for selecting a product via the provided selector."""
    get_state = lambda n, default: self._node_states.get(n, default)
    return self._rule_edges.get_state_for_selector(selector, subject, variants, get_state)
