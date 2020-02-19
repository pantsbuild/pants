# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.deprecated import warn_or_error
from pants.build_graph.address import Address


class InjectablesMixin:
  """A mixin for classes (typically optionables) that require certain targets in order to function.

  :API: public
  """

  class NoMappingForKey(Exception):
    """Thrown when a mapping doesn't exist for a given injectables key."""

  class TooManySpecsForKey(Exception):
    """Thrown when a mapping contains multiple specs when a singular spec is expected."""

  def injectables(self, build_graph):
    """Given a `BuildGraph`, inject any targets required for this object to function.

    This function will be called just before `Target` injection time. Any objects injected here
    should have a static spec path that will need to be emitted, pre-injection, by the
    `injectables_specs` classmethod for the purpose of dependency association for e.g. `changed`.

    :API: public
    """

  @property
  def injectables_address_spec_mapping(self):
    """A mapping of {key: address_spec} that is used for locating injectable address specs.

    This should be overridden by subclasses who wish to define an injectables mapping.

    :API: public
    """
    return {}

  def injectables_address_specs_for_key(self, key):
    """Given a key, yield all relevant injectable address specs.

    :API: public
    """
    mapping = self.injectables_address_spec_mapping
    if key not in mapping:
      raise self.NoMappingForKey(key)
    address_specs = mapping[key]
    assert isinstance(address_specs, list), (
      'invalid `injectables_address_spec_mapping` on {!r} for key "{}". '
      "expected a `list` but instead found a `{}`: {}"
    ).format(self, key, type(address_specs), address_specs)
    return [Address.parse(s).spec for s in address_specs]

  def injectables_address_spec_for_key(self, key):
    """Given a key, yield a singular address spec representing that key.

    :API: public
    """
    address_specs = self.injectables_address_specs_for_key(key)
    specs_len = len(address_specs)
    if specs_len == 0:
      return None
    if specs_len != 1:
      raise self.TooManySpecsForKey(
        f"injectables address spec mapping for key included {specs_len} elements, expected 1"
      )
    return address_specs[0]

  @property
  def injectables_spec_mapping(self):
    """A mapping of {key: spec} that is used for locating injectable specs.

    This should be overridden by subclasses who wish to define an injectables mapping.

    :API: public
    """
    warn_or_error(
      removal_version="1.27.0.dev0",
      deprecated_entity_description="injectables_spec_mapping()",
      hint="Use `injectables_address_spec_mapping()` instead. The API is the same as "
      "before. This change is to prepare for Pants eventually supporting file system specs, "
      "e.g. `./pants cloc foo.py`. In preparation, we renamed `Spec` to `AddressSpec`.",
    )
    return self.injectables_address_spec_mapping

  def injectables_specs_for_key(self, key):
    """Given a key, yield all relevant injectable spec addresses.

    :API: public
    """
    warn_or_error(
      removal_version="1.27.0.dev0",
      deprecated_entity_description="injectables_specs_for_key()",
      hint="Use `injectables_specs_for_key()` instead. The API is the same as "
      "before. This change is to prepare for Pants eventually supporting file system specs, "
      "e.g. `./pants cloc foo.py`. In preparation, we renamed `Spec` to `AddressSpec`.",
    )
    return self.injectables_address_specs_for_key(key)

  def injectables_spec_for_key(self, key):
    """Given a key, yield a singular spec representing that key.

    :API: public
    """
    warn_or_error(
      removal_version="1.27.0.dev0",
      deprecated_entity_description="injectables_spec_for_key()",
      hint="Use `injectables_spec_for_key()` instead. The API is the same as "
      "before. This change is to prepare for Pants eventually supporting file system specs, "
      "e.g. `./pants cloc foo.py`. In preparation, we renamed `Spec` to `AddressSpec`.",
    )
    return self.injectables_address_spec_for_key(key)
