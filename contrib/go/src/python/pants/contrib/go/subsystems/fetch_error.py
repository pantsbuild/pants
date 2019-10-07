# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


class FetchError(Exception):
  """Indicates an error fetching remote code."""

  def add_message_prefix(self, prefix):
    # Note: Assumes that this object was created with a single string argument.
    self.args = ('{}{}'.format(prefix, self.args[0]), )
