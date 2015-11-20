# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.base.validation import assert_list


logger = logging.getLogger(__name__)


class JavaWireLibrary(ExportableJvmLibrary):
  """Generates a stub Java library from protobuf IDL files.

  Supports Wire 1.x only.

  For an example Wire 2.x interface that generates service stubs see:
  https://github.com/ericzundel/mvn2pants/tree/master/src/python/squarepants/plugins/sake_wire_codegen

  But note this requires you to write a custom wire code generator with a command line interface.
  """

  def __init__(self,
               payload=None,
               service_writer=None,
               service_writer_options=None,
               roots=None,
               registry_class=None,
               enum_options=None,
               no_options=None,
               **kwargs):
    """
    :param string service_writer: the name of the class to pass as the --service_writer option to
    the Wire compiler (For wire 1.0 only)
    :param list service_writer_options: A list of options to pass to the service writer (For
    wire 1.x only)
    :param list roots: passed through to the --roots option of the Wire compiler
    :param string registry_class: fully qualified class name of RegistryClass to create. If in
    doubt, specify com.squareup.wire.SimpleServiceWriter
    :param list enum_options: list of enums to pass to as the --enum-enum_options option, # optional
    :param boolean no_options: boolean that determines if --no_options flag is passed
    """

    if not service_writer and service_writer_options:
      raise TargetDefinitionException(self,
                                      'service_writer_options requires setting service_writer')

    payload = payload or Payload()
    payload.add_fields({
      'service_writer': PrimitiveField(service_writer or None),
      'service_writer_options': PrimitiveField(
        assert_list(service_writer_options, key_arg='service_writer_options',
                    raise_type=TargetDefinitionException)),
      'roots': PrimitiveField(roots or []),
      'registry_class': PrimitiveField(registry_class or None),
      'enum_options': PrimitiveField(enum_options or []),
      'no_options': PrimitiveField(no_options or False),
    })

    super(JavaWireLibrary, self).__init__(payload=payload, **kwargs)
    self.add_labels('codegen')
