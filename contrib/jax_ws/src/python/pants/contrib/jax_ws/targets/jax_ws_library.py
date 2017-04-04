# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField


logger = logging.getLogger(__name__)


class JaxWsLibrary(ExportableJvmLibrary):
  """Generates a Java library from JAX-WS wsdl files."""

  def __init__(self,
               payload=None,
               xjc_args=None,
               extra_args=None,
               **kwargs):
    """Generates a Java library from WSDL files using JAX-WS.

    :param list xjc_args: Additional arguments to xjc.
    :param list extra_args: Additional arguments for the CLI.
    """
    payload = payload or Payload()
    payload.add_fields({
      'xjc_args': PrimitiveField(self.assert_list(xjc_args, key_arg='xjc_args')),
      'extra_args': PrimitiveField(self.assert_list(extra_args, key_arg='extra_args')),
    })
    super(JaxWsLibrary, self).__init__(payload=payload, **kwargs)
    self.add_labels('codegen')
