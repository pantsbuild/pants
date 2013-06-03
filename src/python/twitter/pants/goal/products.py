from collections import defaultdict

class Products(object):
  class ProductMapping(object):
    """Maps products of a given type by target. Each product is a map from basedir to a list of
    files in that dir.
    """

    def __init__(self, typename):
      self.typename = typename
      self.by_target = defaultdict(lambda: defaultdict(list))

    def add(self, target, basedir, product_paths=None):
      """
        Adds a mapping of products for the given target, basedir pair.

        If product_paths are specified, these will over-write any existing mapping for this target.

        If product_paths is omitted, the current mutable list of mapped products for this target
        and basedir is returned for appending.
      """
      if product_paths is not None:
        self.by_target[target][basedir].extend(product_paths)
      else:
        return self.by_target[target][basedir]

    def has(self, target):
      """Returns whether we have a mapping for the specified target."""
      return target in self.by_target

    def get(self, target):
      """
        Returns the product mapping for the given target as a map of <basedir> -> <products list>,
        or None if no such product exists.
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
      """
      return self.by_target.iteritems()

    def keys_for(self, basedir, file):
      """Returns the set of keys the given mapped product is registered under."""
      keys = set()
      for key, mappings in self.by_target.items():
        for mapped in mappings.get(basedir, []):
          if file == mapped:
            keys.add(key)
            break
      return keys

    def __repr__(self):
      return 'ProductMapping(%s) {\n  %s\n}' % (self.typename, '\n  '.join(
        '%s => %s\n    %s' % (str(target), basedir, outputs)
                              for target, outputs_by_basedir in self.by_target.items()
                              for basedir, outputs in outputs_by_basedir.items()))

  def __init__(self):
    self.products = {}
    self.predicates_for_type = defaultdict(list)

  def require(self, typename, predicate=None):
    """
      Registers a requirement that products of the given type by mapped.  If a target predicate is
      supplied, only targets matching the predicate are mapped.
    """
    if predicate:
      self.predicates_for_type[typename].append(predicate)
    return self.products.setdefault(typename, Products.ProductMapping(typename))

  def isrequired(self, typename):
    """
      Returns a predicate that selects targets required for the given type if mappings are
      required.  Otherwise returns None.
    """
    if typename not in self.products:
      return None
    def combine(first, second):
      return lambda target: first(target) or second(target)
    return reduce(combine, self.predicates_for_type[typename], lambda target: False)

  def get(self, typename):
    """Returns a ProductMapping for the given type name."""
    return self.require(typename)

  def require_data(self, *typenames):
    """ Registers a requirement that data produced by tasks is required.
    Params:
      typenames a list of names of data products that are should be generated.
    """
    for t in typenames:
      self.data_products[t] = {}

  def is_required_data(self, typename):
    """ Checks if a particular data product is required by any tasks."""
    return self.data_products.has_key(typename)

  def get_data(self, typename):
    """ Returns a data product, or None if the product isn't found."""
    if self.data_products.has_key(typename):
      return self.data_products[typename]
    else:
      return None

  def set_data(self, typename, data):
    """ Stores a required data product. If the product already exists, the value is replaced. """
    self.data_products[typename] = data

