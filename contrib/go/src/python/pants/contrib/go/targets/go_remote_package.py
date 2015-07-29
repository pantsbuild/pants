# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField

from pants.contrib.go.targets.go_target import GoTarget


class GoRemotePackage(GoTarget):

  def __init__(self, rev='', zip_url='', artifact_addr='', **kwargs):
    payload = Payload()
    payload.add_fields({
      'rev': PrimitiveField(rev),
      'zip_url': PrimitiveField(zip_url)
    })
    super(GoRemotePackage, self).__init__(payload=payload, **kwargs)
