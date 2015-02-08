# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
from textwrap import dedent

from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField


logger = logging.getLogger(__name__)


class JavaWireLibrary(ExportableJvmLibrary):
  """Generates a stub Java library from protobuf IDL files."""

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
    the Wire compiler.
    :param list service_writer_options: A list of options to pass to the service writer
    :param list roots: passed through to the --roots option of the Wire compiler
    :param string registry_class: fully qualified class name of RegistryClass to create. If in
    doubt, specify com.squareup.wire.SimpleServiceWriter
    :param list enum_options: list of enums to pass to as the --enum-enum_options option, # optional
    :param boolean no_options: boolean that determines if --no_options flag is passed
    """
    payload = payload or Payload()
    payload.add_fields({
      'service_writer': PrimitiveField(service_writer or None),
      'service_writer_options': PrimitiveField(service_writer_options or []),
      'roots': PrimitiveField(roots or []),
      'registry_class': PrimitiveField(registry_class or None),
      'enum_options': PrimitiveField(enum_options or []),
      'no_options':  PrimitiveField(no_options or False),
    })

    if service_writer_options:
      logger.warn('The service_writer_options flag is ignored.')
    if roots:
      logger.warn(dedent('''
          It is known that passing in roots may not work as intended. Pants tries to predict what
          files Wire will generate then does a verification to see if all of those files were
          generated.  With the roots flag set, it may be the case that not all predicted files will
          be generated and the verification will fail.'''))

    super(JavaWireLibrary, self).__init__(payload=payload, **kwargs)
    self.add_labels('codegen')
