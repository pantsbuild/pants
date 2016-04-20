# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

import six
from twitter.common.collections import OrderedSet

from pants.util.dirutil import fast_relpath


class ProductError(Exception):
  """
  :API: public
  """
  pass


class UnionProducts(object):
  """Here, products for a target are an insertion ordered set.

  When products for multiple targets are requested, an ordered union is provided.

  :API: public
  """

  def __init__(self, products_by_target=None):
    """
    :API: public
    """
    # A map of target to OrderedSet of product members.
    self._products_by_target = products_by_target or defaultdict(OrderedSet)

  def copy(self):
    """Returns a copy of this UnionProducts.

    Edits to the copy's mappings will not affect the product mappings in the original.
    The copy is shallow though, so edits to the the copy's product values will mutate the original's
    product values.

    :API: public

    :rtype: :class:`UnionProducts`
    """
    products_by_target = defaultdict(OrderedSet)
    for key, value in self._products_by_target.items():
      products_by_target[key] = OrderedSet(value)
    return UnionProducts(products_by_target=products_by_target)

  def add_for_target(self, target, products):
    """Updates the products for a particular target, adding to existing entries.

    :API: public
    """
    self._products_by_target[target].update(products)

  def add_for_targets(self, targets, products):
    """Updates the products for the given targets, adding to existing entries.

    :API: public
    """
    # FIXME: This is a temporary helper for use until the classpath has been split.
    for target in targets:
      self.add_for_target(target, products)

  def remove_for_target(self, target, products):
    """Updates the products for a particular target, removing the given existing entries.

    :API: public
    """
    for product in products:
      self._products_by_target[target].discard(product)

  def get_for_target(self, target):
    """Gets the products for the given target.

    :API: public
    """
    return self.get_for_targets([target])

  def get_for_targets(self, targets):
    """Gets the union of the products for the given targets, preserving the input order.

    :API: public
    """
    products = OrderedSet()
    for target in targets:
      products.update(self._products_by_target[target])
    return products

  def get_product_target_mappings_for_targets(self, targets):
    """Gets the product-target associations for the given targets, preserving the input order.

    :API: public

    :param targets: The targets to lookup products for.
    :returns: The ordered (product, target) tuples.
    """
    product_target_mappings = []
    for target in targets:
      for product in self._products_by_target[target]:
        product_target_mappings.append((product, target))

    return product_target_mappings

  def target_for_product(self, product):
    """Looks up the target key for a product.

    :API: public

    :param product: The product to search for
    :return: None if there is no target for the product
    """
    for target, products in self._products_by_target.items():
      if product in products:
        return target
    return None

  def __str__(self):
    return "UnionProducts({})".format(self._products_by_target)

  def __eq__(self, other):
    return (isinstance(other, UnionProducts) and
            self._products_by_target == other._products_by_target)

  def __ne__(self, other):
    return not self == other


class RootedProducts(object):
  """File products of a build that have a concept of a 'root' directory.

  E.g., classfiles, under a root package directory.

  :API: public
  """

  def __init__(self, root):
    """
    :API: public
    """
    self._root = root
    self._rel_paths = OrderedSet()

  def add_abs_paths(self, abs_paths):
    """
    :API: public
    """
    for abs_path in abs_paths:
      self._rel_paths.add(fast_relpath(abs_path, self._root))

  def add_rel_paths(self, rel_paths):
    """
    :API: public
    """
    self._rel_paths.update(rel_paths)

  def root(self):
    """
    :API: public
    """
    return self._root

  def rel_paths(self):
    """
    :API: public
    """
    return self._rel_paths

  def abs_paths(self):
    """
    :API: public
    """
    for relpath in self._rel_paths:
      yield os.path.join(self._root, relpath)

  def __bool__(self):
    return self._rel_paths

  __nonzero__ = __bool__


class MultipleRootedProducts(object):
  """A product consisting of multiple roots, with associated file products.

  :API: public
  """

  def __init__(self):
    """
    :API: public
    """
    self._rooted_products_by_root = {}

  def add_rel_paths(self, root, rel_paths):
    """
    :API: public
    """
    self._get_products_for_root(root).add_rel_paths(rel_paths)

  def add_abs_paths(self, root, abs_paths):
    """
    :API: public
    """
    self._get_products_for_root(root).add_abs_paths(abs_paths)

  def rel_paths(self):
    """
    :API: public
    """
    for root, products in self._rooted_products_by_root.items():
      yield root, products.rel_paths()

  def abs_paths(self):
    """
    :API: public
    """
    for root, products in self._rooted_products_by_root.items():
      yield root, products.abs_paths()

  def _get_products_for_root(self, root):
    return self._rooted_products_by_root.setdefault(root, RootedProducts(root))

  def __bool__(self):
    """Return True if any of the roots contains products"""
    for root, products in self.rel_paths():
      if products:
        return True
    return False

  __nonzero__ = __bool__

  def __str__(self):
    return "MultipleRootedProducts({})".format(self._rooted_products_by_root)


class Products(object):
  """An out-of-band 'dropbox' where tasks can place build product information for later tasks to use.

  Historically, the only type of product was a ProductMapping. However this had some issues, as not
  all products fit into the (basedir, [files-under-basedir]) paradigm. Also, ProductMapping docs
  and varnames refer to targets, and implicitly expect the mappings to be keyed by a target, however
  we sometimes also need to map sources to products.

  So in practice we ended up abusing this in several ways:
    1) Using fake basedirs when we didn't have a basedir concept.
    2) Using objects other than strings as 'product paths' when we had a need to.
    3) Using things other than targets as keys.

  Right now this class is in an intermediate stage, as we transition to a more robust Products concept.
  The abuses have been switched to use 'data_products' (see below) which is just a dictionary
  of product type (e.g., 'classes_by_source') to arbitrary payload. That payload can be anything,
  but the MultipleRootedProducts class is useful for products that do happen to fit into the
  (basedir, [files-under-basedir]) paradigm.

  The long-term future of Products is TBD. But we do want to make it easier to reason about
  which tasks produce which products and which tasks consume them. Currently it's quite difficult
  to match up 'requires' calls to the producers of those requirements, especially when the 'typename'
  is in a variable, not a literal.

  :API: public
  """
  class ProductMapping(object):
    """Maps products of a given type by target. Each product is a map from basedir to a list of
    files in that dir.

    :API: public
    """

    def __init__(self, typename):
      """
      :API: public
      """
      self.typename = typename
      self.by_target = defaultdict(lambda: defaultdict(list))

    def empty(self):
      """
      :API: public
      """
      return len(self.by_target) == 0

    def add(self, target, basedir, product_paths=None):
      """
        Adds a mapping of products for the given target, basedir pair.

        If product_paths are specified, these will over-write any existing mapping for this target.

        If product_paths is omitted, the current mutable list of mapped products for this target
        and basedir is returned for appending.

        :API: public
      """
      if product_paths is not None:
        self.by_target[target][basedir].extend(product_paths)
      else:
        return self.by_target[target][basedir]

    def has(self, target):
      """Returns whether we have a mapping for the specified target.

      :API: public
      """
      return target in self.by_target

    def get(self, target):
      """
        Returns the product mapping for the given target as a tuple of (basedir, products list).
        Can return None if there is no mapping for the given target.

        :API: public
      """
      return self.by_target.get(target)

    def __getitem__(self, target):
      """
        Support for subscripting into this mapping. Returns the product mapping for the given target
        as a map of <basedir> -> <products list>.
        If no mapping exists, returns an empty map whose values default to empty lists. So you
        can use the result without checking for None.
      """
      return self.by_target[target]

    def itermappings(self):
      """
        Returns an iterable over all pairs (target, product) in this mapping.
        Each product is itself a map of <basedir> -> <products list>.

        :API: public
      """
      return six.iteritems(self.by_target)

    def keys_for(self, basedir, product):
      """Returns the set of keys the given mapped product is registered under.

      :API: public
      """
      keys = set()
      for key, mappings in self.by_target.items():
        for mapped in mappings.get(basedir, []):
          if product == mapped:
            keys.add(key)
            break
      return keys

    def __repr__(self):
      return 'ProductMapping({}) {{\n  {}\n}}'.format(self.typename, '\n  '.join(
          '{} => {}\n    {}'.format(str(target), basedir, outputs)
          for target, outputs_by_basedir in self.by_target.items()
          for basedir, outputs in outputs_by_basedir.items()))

    def __bool__(self):
      return not self.empty()

    __nonzero__ = __bool__

  def __init__(self):
    # TODO(John Sirois): Kill products and simply have users register ProductMapping subtypes
    # as data products.  Will require a class factory, like `ProductMapping.named(typename)`.
    self.products = {}  # type -> ProductMapping instance.
    self.required_products = set()

    self.data_products = {}  # type -> arbitrary object.
    self.required_data_products = set()

  def require(self, typename):
    """Registers a requirement that file products of the given type by mapped.

    :API: public

    :param typename: the type or other key of a product mapping that should be generated.
    """
    self.required_products.add(typename)

  def isrequired(self, typename):
    """Checks if a particular product is required by any tasks.

    :API: public
    """
    return typename in self.required_products

  def get(self, typename):
    """Returns a ProductMapping for the given type name.

    :API: public
    """
    return self.products.setdefault(typename, Products.ProductMapping(typename))

  def require_data(self, typename):
    """Registers a requirement that data produced by tasks is required.

    :API: public

    :param typename: the type or other key of a data product that should be generated.
    """
    self.required_data_products.add(typename)

  def is_required_data(self, typename):
    """Checks if a particular data product is required by any tasks.

    :API: public
    """
    return typename in self.required_data_products

  def safe_create_data(self, typename, init_func):
    """Ensures that a data item is created if it doesn't already exist.

    :API: public
    """
    # Basically just an alias for readability.
    return self.get_data(typename, init_func)

  def get_data(self, typename, init_func=None):
    """ Returns a data product.

    :API: public

    If the product isn't found, returns None, unless init_func is set, in which case the product's
    value is set to the return value of init_func(), and returned."""
    if typename not in self.data_products:
      if not init_func:
        return None
      self.data_products[typename] = init_func()
    return self.data_products.get(typename)

  def get_only(self, product_type, target):
    """If there is exactly one product for the given product type and target, returns the
    full filepath of said product.

    Otherwise, raises a ProductError.

    Useful for retrieving the filepath for the executable of a binary target.

    :API: public
    """
    product_mapping = self.get(product_type).get(target)
    if len(product_mapping) != 1:
      raise ProductError('{} directories in product mapping: requires exactly 1.'
                         .format(len(product_mapping)))

    for _, files in product_mapping.items():
      if len(files) != 1:
        raise ProductError('{} files in target directory: requires exactly 1.'
                           .format(len(files)))

      return files[0]
