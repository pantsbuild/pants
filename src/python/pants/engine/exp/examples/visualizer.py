# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
import sys
from collections import defaultdict
from textwrap import dedent

from pants.binaries import binary_util
from pants.build_graph.address import Address
from pants.engine.exp.engine import LocalSerialEngine
from pants.engine.exp.examples.planners import ExampleTable, setup_json_scheduler
from pants.engine.exp.scheduler import (BuildRequest, DependenciesNode,
                                        PartiallyConsumedInputsError, Return, SelectNode, TaskNode,
                                        Throw)
from pants.util.contextutil import temporary_file, temporary_file_path


def format_type(node):
  if type(node) == TaskNode:
    return node.func.__name__
  return type(node).__name__


def format_subject(node):
  subject = node.subject
  if type(node.subject) == Address:
    subject = 'Address({})'.format(node.subject)
  if node.variants:
    subject = '{}@{}'.format(subject, ','.join('{}={}'.format(k, v) for k, v in node.variants))
  return subject


def format_product(node):
  if type(node) == SelectNode and node.variant_key:
    return '{}@{}'.format(node.product.__name__, node.variant_key)
  return node.product.__name__


def format_node(node, state):
  return '{}:{}:{} == {}'.format(format_product(node),
                                 format_subject(node),
                                 format_type(node),
                                 str(state).replace('"', '\\"'))


def create_digraph(scheduler):

  # NB: there are only 12 colors in `set312`.
  colorscheme = 'set312'
  max_colors = 12
  colors = {}

  def color_index(key):
    return colors.setdefault(key, (len(colors) % max_colors) + 1)

  yield 'digraph plans {'
  yield '  node[colorscheme={}];'.format(colorscheme)
  yield '  concentrate=true;'
  yield '  rankdir=LR;'

  for ((node, node_state), dependency_entries) in scheduler.walk_product_graph():
    node_str = format_node(node, node_state)

    yield ('  node [style=filled, fillcolor={color}] "{node}";'
            .format(color=color_index(node.product),
                    node=node_str))

    for (dep, dep_state) in dependency_entries:
      yield '  "{}" -> "{}"'.format(node_str, format_node(dep, dep_state))

  yield '}'


def visualize_execution_graph(scheduler):
  with temporary_file() as fp:
    for line in create_digraph(scheduler):
      fp.write(line)
      fp.write('\n')
    fp.close()
    with temporary_file_path(cleanup=False, suffix='.svg') as image_file:
      subprocess.check_call('dot -Tsvg -o{} {}'.format(image_file, fp.name), shell=True)
      binary_util.ui_open(image_file)


def used_literal_dependency(product_graph, literal_types, root_subject, roots):
  """Walks nodes for the given product and returns the first literal product used, or None.

  Note that this will not walk into Nodes for other subjects.
  """
  def predicate(entry):
    node, state = entry
    return root_subject == node.subject and type(state) is not Throw
  for ((node, _), _) in product_graph.walk(roots, predicate=predicate):
    if node.product in literal_types:
      return node.product
  return None


def validate_failed_root(product_graph, partially_consumed_inputs, failed_root):
  """Walks below a failed node and collects cases where additional literal products could be used.
  
  In particular, looks (recursively) for cases where:
    1) at least one literal subject existed.
    2) some literal/named products were missing.

  Returns dict(partially_consumed_input, dict(used_product, list(tasks_with_missing_products))).

  TODO: propagate SymbolTable more cleanly.
  """
  literal_types = set(ExampleTable.table().values())
  for ((node, state), dependencies) in product_graph.walk([failed_root], predicate=lambda _: True):
    # Look for failed TaskNodes with at least one satisfied Select dependency.
    if type(node) != TaskNode:
      continue
    if type(state) != Throw:
      continue
    select_deps = {dep: state for dep, state in dependencies if type(dep) == SelectNode}
    if not select_deps:
      continue
    failed_products = {dep.product for dep, state in select_deps.items() if type(state) == Throw}
    if not failed_products:
      continue

    # If all unattainable products could have been specified as literal...
    all_literal_failed_products = all(product in literal_types for product in failed_products)
    if not all_literal_failed_products:
      continue

    # And there was at least one dep successfully (recursively) satisfied via a literal.
    used_literal_dep = used_literal_dependency(product_graph,
                                               literal_types,
                                               node.subject,
                                               select_deps.keys())
    if used_literal_dep is None:
      continue
    partially_consumed_inputs[(node.subject, node.product)][used_literal_dep].append((node.func, failed_products))


def validate_graph(scheduler):
  """Finds failed roots and invokes subgraph validation on each of them."""

  # Locate failed root Nodes: those with an Address Subject which failed, but which did
  # not have any failed (direct) dependents.
  failed_roots = set()
  for node, dependents in scheduler.product_graph.dependents().items():
    if not type(node) == SelectNode:
      continue
    if not isinstance(node.subject, Address):
      continue
    if not type(scheduler.product_graph.state(node)) == Throw:
      continue
    if any(type(scheduler.product_graph.state(d)) is Throw for d in dependents):
      # Node had failed dependents: was not a failed root.
      continue
    failed_roots.add(node)

  # Raise if there were any partially consumed inputs.
  partials = defaultdict(lambda: defaultdict(list))
  for failed_root in failed_roots:
    validate_failed_root(scheduler.product_graph, partials, failed_root)
  if partials:
    raise PartiallyConsumedInputsError(partials)


def visualize_build_request(build_root, build_request):
  scheduler = setup_json_scheduler(build_root)
  LocalSerialEngine(scheduler).reduce(build_request)
  validate_graph(scheduler)
  visualize_execution_graph(scheduler)


def main():
  def usage(error_message):
    print(error_message, file=sys.stderr)
    print(dedent("""
    {} [build root path] [goal]+ [address spec]*
    """.format(sys.argv[0])), file=sys.stderr)
    sys.exit(1)

  args = sys.argv[1:]
  if len(args) < 2:
    usage('Must supply at least the build root path and one goal.')

  build_root = args.pop(0)
  if not os.path.isdir(build_root):
    usage('First argument must be a valid build root, {} is not a directory.'.format(build_root))

  goals = [arg for arg in args if os.path.sep not in arg]
  if not goals:
    usage('Must supply at least one goal.')

  build_request = BuildRequest(goals=goals,
                               addressable_roots=[Address.parse(spec) for spec in args
                                                  if os.path.sep in spec])
  visualize_build_request(build_root, build_request)
