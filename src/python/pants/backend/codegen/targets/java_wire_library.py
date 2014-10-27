# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import logging

from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField

logger = logging.getLogger(__name__)


class JavaWireLibrary(ExportableJvmLibrary):
    """Generates a stub Java library from protobuf IDL files."""

    def __init__(self, payload=None, service_writer=None, service_writer_options=None, roots=None, **kwargs):
        """
        :param string service_writer: the name of the class to pass as the --service-writer option to the Wire compiler
        :param list service_writer_options: A list of service methods to generate.
        :param list roots: passed through to the --roots option of the Wire compiler
        """
        payload = payload or Payload()
        payload.add_fields({
            'service_writer': PrimitiveField(service_writer or None),
            'service_writer_options': PrimitiveField(service_writer_options or ()),
            'roots': PrimitiveField(roots or ())
        })
        super(JavaWireLibrary, self).__init__(payload=payload, **kwargs)
        self.add_labels('codegen')
        self._imports = None
