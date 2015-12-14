# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import defaultdict, namedtuple

from pants.goal.goal import Goal


class ProducerInfo(namedtuple('ProducerInfo', ['product_type', 'task_type', 'goal'])):
  """Describes the producer of a given product type."""


class RoundManager(object):

  class MissingProductError(KeyError):
    """Indicates a required product type is provided by non-one."""

  @staticmethod
  def _index_products():
    producer_info_by_product_type = defaultdict(set)
    for goal in Goal.all():
      for task_type in goal.task_types():
        for product_type in task_type.product_types():
          producer_info = ProducerInfo(product_type, task_type, goal)
          producer_info_by_product_type[product_type].add(producer_info)
    return producer_info_by_product_type

  def __init__(self, context):
    self._dependencies = set()
    self._context = context
    self._producer_infos_by_product_type = None

  def require(self, product_type):
    """Schedules the tasks that produce product_type to be executed before the requesting task."""
    self._dependencies.add(product_type)
    self._context.products.require(product_type)

  def require_data(self, product_type):
    """Schedules the tasks that produce product_type to be executed before the requesting task."""
    self._dependencies.add(product_type)
    self._context.products.require_data(product_type)

  def get_dependencies(self):
    """Returns the set of data dependencies as producer infos corresponding to data requirements."""
    producer_infos = set()
    for product_type in self._dependencies:
      producer_infos.update(self._get_producer_infos_by_product_type(product_type))
    return producer_infos

  def _get_producer_infos_by_product_type(self, product_type):
    if self._producer_infos_by_product_type is None:
      self._producer_infos_by_product_type = self._index_products()

    producer_infos = self._producer_infos_by_product_type[product_type]
    if not producer_infos:
      raise self.MissingProductError("No producers registered for '{0}'".format(product_type))
    return producer_infos
