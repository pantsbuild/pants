# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from glob import glob

from pants.base.payload import Payload
from pants.base.target import Target


class GoLocalSource(Target):

  def __init__(self, address=None, payload=None, **kwargs):
    sources = glob(os.path.join(address.spec_path, '*.go'))
    payload = payload or Payload()
    payload.add_fields({
      'sources': self.create_sources_field(sources=sources,
                                           sources_rel_path='',
                                           key_arg='sources'),
    })
    super(GoLocalSource, self).__init__(address=address, payload=payload, **kwargs)
