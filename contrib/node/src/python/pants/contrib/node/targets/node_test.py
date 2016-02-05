# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.target import Target


class NodeTest(Target):
  """Javascript tests run via a script specified in a package.json file."""

  def __init__(self, script_name=None, address=None, payload=None, **kwargs):
    """
    :param string script_name: The tests script name in package.json. Defaults to "test".
    """
    payload = payload or Payload()
    payload.add_fields({
      'script_name': PrimitiveField(script_name or 'test'),
    })
    super(NodeTest, self).__init__(address=address, payload=payload, **kwargs)

  @property
  def script_name(self):
    """The script name in package.json that runs the tests.

    :rtype: string
    """
    return self.payload.script_name
