# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict

from pants.goal import Phase


class RoundManager(object):
  _phases_by_product = None

  @classmethod
  def _get_phases_by_product(cls, product):
    if cls._phases_by_product is None:
      phases_by_product = defaultdict(set)
      for phase, goals in Phase.all():
        for goal in goals:
          for pt in goal.task_type.product_type():
            phases_by_product[pt].add(phase)
      cls._phases_by_product = phases_by_product
    return cls._phases_by_product.get(product, [])

  def __init__(self, context):
    self._schedule = set()
    self._context = context

  def require(self, product_type, predicate=None):
    self._schedule.add(product_type)
    self._context.products.require(product_type, predicate)

  def require_data(self, product_type):
    """ Schedules the product_type in invocation order over the target graph."""
    self._schedule.add(product_type)
    self._context.products.require_data(product_type)

  def get_schedule(self):
    return self._schedule

  def lookup_phases_for_products(self, products):
    phases = set()
    for product in products:
      phases.update(self._get_phases_by_product(product))
    return phases
