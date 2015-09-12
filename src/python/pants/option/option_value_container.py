# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.option.ranked_value import RankedValue


class OptionValueContainer(object):
  """A container for option values.

  Implements the following functionality:

  1) Attribute forwarding.

     An attribute can be registered as forwarding to another attribute, and attempts
     to read the source attribute's value will be read from the target attribute.

     This is necessary so we can qualify registered options by the scope that registered them,
     to allow re-registration in inner scopes. This is best explained by example:

     Say that in global scope we register an option with two names: [-f, --foo], which writes its
     value to the attribute foo. Then in the compile scope we re-register --foo but leave -f alone.
     The re-registered --foo will also write to attribute foo. So now -f, which in the compile
     scope is unrelated to --foo, can still stomp on its value.

     With attribute forwarding we can have the global scope option write to _DEFAULT_foo__, and
     the re-registered option to _COMPILE_foo__, and then have the 'f' and 'foo' attributes
     forward, appropriately.

     Note that only reads are forwarded. The target of the forward must be written to directly.
     If the source attribute is set directly, this overrides any forwarding.

  2) Value ranking.

     Attribute values can be ranked, so that a given attribute's value can only be changed if
     the new value has at least as high a rank as the old value. This allows an option value in
     an outer scope to override that option's value in an inner scope, when the outer scope's
     value comes from a higher ranked source (e.g., the outer value comes from an env var and
     the inner one from config).

     See ranked_value.py for more details.

  Note that this container is suitable for passing as the namespace argument to argparse's
  parse_args() method.
  """

  def __init__(self):
    self._forwardings = {}  # src attribute name -> target attribute name.

  def add_forwardings(self, forwardings):
    """Add attribute forwardings.

    Will overwrite existing forwardings with the same source attributes.

    :param forwardings: A map of source attribute name -> attribute to read source's value from.
    """
    self._forwardings.update(forwardings)

  def get_rank(self, key):
    """Returns the rank of the value at the specified key.

    Returns one of the constants in RankedValue.
    """
    if key not in self._forwardings:
      raise AttributeError('No such forwarded attribute: {}'.format(key))
    val = getattr(self, self._forwardings[key])
    if isinstance(val, RankedValue):
      return val.rank
    else:  # Values without rank are assumed to be flag values set by argparse.
      return RankedValue.FLAG

  def is_flagged(self, key):
    """Returns `True` if the value for the specified key was supplied via a flag.

    A convenience equivalent to `get_rank(key) == RankedValue.FLAG`.

    This check can be useful to determine whether or not a user explicitly set an option for this
    run.  Although a user might also set an option explicitly via an environment variable, ie via:
    `ENV_VAR=value ./pants ...`, this is an ambiguous case since the environment variable could also
    be permanently set in the user's environment.

    :param string key: The name of the option to check.
    :returns: `True` if the option was explicitly flagged by the user from the command line.
    :rtype: bool
    """
    return self.get_rank(key) == RankedValue.FLAG

  def is_default(self, key):
    """Returns `True` if the value for the specified key was not supplied by the user.

    I.e. the option was NOT specified config files, on the cli, or in environment variables.

    :param string key: The name of the option to check.
    :returns: `True` if the user did not set the value for this option.
    :rtype: bool
    """
    return self.get_rank(key) in (RankedValue.NONE, RankedValue.HARDCODED)

  def update(self, attrs):
    """Set attr values on this object from the data in the attrs dict."""
    for k, v in attrs.items():
      setattr(self, k, v)

  def get(self, key, default=None):
    # Support dict-like dynamic access.  See also __getitem__ below.
    if hasattr(self, key):
      return getattr(self, key)
    else:
      return default

  def __setattr__(self, key, value):
    if key == '_forwardings':
      return super(OptionValueContainer, self).__setattr__(key, value)

    if hasattr(self, key):
      existing_value = getattr(self, key)
      if isinstance(existing_value, RankedValue):
        existing_rank = existing_value.rank
      else:
        # Values without rank are assumed to be flag values set by argparse.
        existing_rank = RankedValue.FLAG
    else:
      existing_rank = RankedValue.NONE

    if isinstance(value, RankedValue):
      new_rank = value.rank
    else:
      # Values without rank are assumed to be flag values set by argparse.
      new_rank = RankedValue.FLAG

    if new_rank >= existing_rank:
      # We set values from outer scopes before values from inner scopes, so
      # in case of equal rank we overwrite. That way that the inner scope value wins.
      super(OptionValueContainer, self).__setattr__(key, value)

  def __getitem__(self, key):
    # Support natural dynamic access, options[key_var] is more idiomatic than
    # getattr(option, key_var).
    return getattr(self, key)

  def __getattr__(self, key):
    # Note: Called only if regular attribute lookup fails, so accesses
    # to non-forwarded attributes will be handled the normal way.

    if key == '_forwardings':
      # In case we get called in copy/deepcopy, which don't invoke the ctor.
      raise AttributeError
    if key not in self._forwardings:
      raise AttributeError('No such forwarded attribute: {}'.format(key))
    val = getattr(self, self._forwardings[key])
    if isinstance(val, RankedValue):
      return val.value
    else:
      return val

  def __iter__(self):
    """Returns an iterator over all option names, in lexicographical order.

    In the rare (for us) case of an option with multiple names, we pick the
    lexicographically smallest one, for consistency.
    """
    inverse_forwardings = {}  # internal attribute -> external attribute.
    for k, v in self._forwardings.items():
      if v not in inverse_forwardings or inverse_forwardings[v] > k:
        inverse_forwardings[v] = k
    for name in sorted(inverse_forwardings.values()):
      yield name
