# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict

from twitter.common.collections.orderedset import OrderedSet

from pants.goal import Phase


PANTS_WORKDIR = 'pants_workdir'


class RoundManager(object):
  def __init__(self, context):
    self._schedule = OrderedSet()
    self._context = context
    self._phases_by_product = self._create_phases_by_product()

  @property
  def context(self):
    return self._context

  def require(self, product_type, predicate=None):
    self._schedule.add(product_type)
    self._context.products.require(product_type, predicate)

  def require_data(self, product_type):
    """ Schedules the product_type in invocation order over the target graph."""
    self._schedule.add(product_type)
    self._context.products.require_data(product_type)

  def get_schedule(self):
    return self._schedule

  @staticmethod
  def _create_phases_by_product():
    phases_by_product = defaultdict(OrderedSet)
    for phase, goals in Phase.all():
     for goal in goals:
       for pt in goal.task_type.product_type():
         phases_by_product[pt].add(phase)
    return phases_by_product

  def lookup_phases_for_products(self, products):
    phases = OrderedSet()
    for product in products:
      for new_phase in self._phases_by_product.get(product, []):
        phases.add(new_phase)
    return phases
