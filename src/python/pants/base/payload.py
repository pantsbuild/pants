# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from hashlib import sha1

from pants.base.payload_field import PayloadField


class PayloadFieldAlreadyDefinedError(Exception): pass


class PayloadFrozenError(Exception): pass


class Payload(object):
  """A mapping from field names to PayloadField instances.

  A Target will add PayloadFields to its Payload until instantiation is finished, at which point
  freeze() will be called and make the Payload immutable.

  :API: public
  """

  def __init__(self):
    self._fields = {}
    self._frozen = False
    self._fingerprint_memo_map = {}

  @property
  def fields(self):
    return self._fields.items()

  def as_dict(self):
    """Return the Payload object as a dict."""
    return {k: self.get_field_value(k) for k in self._fields}

  def freeze(self):
    """Permanently make this Payload instance immutable.

    No more fields can be added after calling freeze().

    :API: public
    """
    self._frozen = True

  def get_field(self, key, default=None):
    """An alternative to attribute access for duck typing Payload instances.

    Has the same semantics as dict.get, and in fact just delegates to the underlying field mapping.

    :API: public
    """
    return self._fields.get(key, default)

  def get_field_value(self, key, default=None):
    """Retrieves the value in the payload field if the field exists, otherwise returns the default.

    :API: public
    """
    if key in self._fields:
      payload_field = self._fields[key]
      if payload_field:
        return payload_field.value
    return default

  def add_fields(self, field_dict):
    """Add a mapping of field names to PayloadField instances.

    :API: public
    """
    for key, field in field_dict.items():
      self.add_field(key, field)

  def add_field(self, key, field):
    """Add a field to the Payload.

    :API: public

    :param string key:  The key for the field.  Fields can be accessed using attribute access as
      well as `get_field` using `key`.
    :param PayloadField field:  A PayloadField instance.  None is an allowable value for `field`,
      in which case it will be skipped during hashing.
    """
    if key in self._fields:
      raise PayloadFieldAlreadyDefinedError(
        'Key {key} is already set on this payload. The existing field was {existing_field}.'
        ' Tried to set new field {field}.'
        .format(key=key, existing_field=self._fields[key], field=field))
    elif self._frozen:
      raise PayloadFrozenError(
        'Payload is frozen, field with key {key} cannot be added to it.'
        .format(key=key))
    else:
      self._fields[key] = field
      self._fingerprint_memo = None

  def fingerprint(self, field_keys=None):
    """A memoizing fingerprint that rolls together the fingerprints of underlying PayloadFields.

    If no fields were hashed (or all fields opted out of being hashed by returning `None`), then
    `fingerprint()` also returns `None`.

    :param iterable<string> field_keys: A subset of fields to use for the fingerprint.  Defaults
                                        to all fields.
    """
    field_keys = frozenset(field_keys or self._fields.keys())
    if field_keys not in self._fingerprint_memo_map:
      self._fingerprint_memo_map[field_keys] = self._compute_fingerprint(field_keys)
    return self._fingerprint_memo_map[field_keys]

  def _compute_fingerprint(self, field_keys):
    hasher = sha1()
    empty_hash = True
    for key in sorted(field_keys):
      field = self._fields[key]
      if field is not None:
        fp = field.fingerprint()
        if fp is not None:
          empty_hash = False
          hasher.update(sha1(key).hexdigest())
          hasher.update(fp)
    if empty_hash:
      return None
    else:
      return hasher.hexdigest()

  def mark_dirty(self):
    """Invalidates memoized fingerprints for this payload.

    Exposed for testing.

    :API: public
    """
    self._fingerprint_memo_map = {}
    for field in self._fields.values():
      field.mark_dirty()

  def __getattr__(self, attr):
    field = self._fields[attr]
    if field is not None:
      return field.value
    else:
      return None

  def __hasattr__(self, attr):
    return attr in self._fields
