# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import defaultdict

from pants.engine.nodes import Noop, Return, SelectNode, TaskNode


class GraphValidator(object):
  """A concrete object that implements validation of a completed product graph.

  TODO: The name "literal" here is overloaded with SelectLiteral, which is a better fit
  for the name. The values here are more "user-specified/configured" than "literal".

  This class offers the abstraction to allow plugin implementers to install their own.
  TODO: The current implementation is slow, and ideally validation _during_ graph
  should run while subgraphs are completing. This would limit their performance
  impact, and allow for better locality of errors.
  """

  def __init__(self, symbol_table_cls):
    self._literal_types = dict()
    for name, cls in symbol_table_cls.table().items():
      self._literal_types[cls] = name

  def _collect_consumed_inputs(self, product_graph, root):
    """Walks successful nodes under the root for its subject, and returns all products used."""
    consumed_inputs = set()
    # Walk into successful nodes for the same subject under this root.
    def predicate(node, state):
      return root.subject == node.subject and type(state) is Return
    # If a product was successfully selected, record it.
    for node, _ in product_graph.walk([root], predicate=predicate):
      if type(node) is SelectNode:
        consumed_inputs.add(node.product)
    return consumed_inputs

  def _collect_partially_consumed_inputs(self, product_graph, consumed_inputs, root):
    """Walks below a failed node and collects cases where additional literal products could be used.
    Returns:
      dict(subject, dict(tuple(input_product, output_product), list(tuple(task, missing_products))))
    """
    partials = defaultdict(lambda: defaultdict(list))
    # Walk all nodes for the same subject under this root.
    def predicate(node, state):
      return root.subject == node.subject
    for node, state in product_graph.walk([root], predicate=predicate):
      # Look for unsatisfied TaskNodes with at least one unsatisfied dependency.
      if type(node) is not TaskNode:
        continue
      if type(state) is not Noop:
        continue
      sub_deps = [d for d in product_graph.dependencies_of(node) if d.subject == root.subject]
      missing_products = {d.product for d in sub_deps if type(product_graph.state(d)) is Noop}
      if not missing_products:
        continue

      # If all unattainable products could have been specified as literal...
      if any(product not in self._literal_types for product in missing_products):
        continue

      # There was at least one dep successfully (recursively) satisfied via a literal.
      # TODO: this does multiple walks.
      used_literal_deps = set()
      for dep in sub_deps:
        for product in self._collect_consumed_inputs(product_graph, dep):
          if product in self._literal_types:
            used_literal_deps.add(product)
      if not used_literal_deps:
        continue

      # The partially consumed products were not fully consumed elsewhere.
      if not (used_literal_deps - consumed_inputs):
        continue

      # Found a partially consumed input.
      for used_literal_dep in used_literal_deps:
        partials[node.subject][(used_literal_dep, node.product)].append((node.func, missing_products))
    return partials

  def validate(self, product_graph):
    """Finds 'subject roots' in the product graph and invokes validation on each of them."""

    # Locate roots: those who do not have any dependents for the same subject.
    roots = set()
    for node, dependents in product_graph.dependents():
      if any(d.subject == node.subject for d in dependents):
        # Node had a dependent for its subject: was not a root.
        continue
      roots.add(node)

    # Raise if there were any partially consumed inputs.
    for root in roots:
      consumed = self._collect_consumed_inputs(product_graph, root)
      partials = self._collect_partially_consumed_inputs(product_graph, consumed, root)
      if partials:
        raise PartiallyConsumedInputsError.create(self._literal_types, partials)


class PartiallyConsumedInputsError(Exception):
  """No task was able to consume a particular literal product for a subject, although some tried.

  In particular, this error allows for safe composition of configuration on targets (ie,
  ThriftSources AND ThriftConfig), because if a task requires multiple inputs for a subject
  but cannot find them, a useful error is raised.

  TODO: Improve the error message in the presence of failures due to mismatched variants.
  """

  @classmethod
  def _msg(cls, inverted_symbol_table, partially_consumed_inputs):
    def name(product):
      return inverted_symbol_table[product]
    for subject, tasks_and_inputs in partially_consumed_inputs.items():
      yield '\nSome products were partially specified for `{}`:'.format(subject)
      for ((input_product, output_product), tasks) in tasks_and_inputs.items():
        yield '  To consume `{}` and produce `{}`:'.format(name(input_product), name(output_product))
        for task, additional_inputs in tasks:
          inputs_str = ' AND '.join('`{}`'.format(name(i)) for i in additional_inputs)
          yield '    {} also needed ({})'.format(task.__name__, inputs_str)

  @classmethod
  def create(cls, inverted_symbol_table, partially_consumed_inputs):
    msg = '\n'.join(cls._msg(inverted_symbol_table, partially_consumed_inputs))
    return cls(msg)
