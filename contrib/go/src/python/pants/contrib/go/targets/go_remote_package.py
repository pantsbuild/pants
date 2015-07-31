# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.base.target import Target


class GoRemotePackage(Target):

  def __init__(self, rev='', zip_url='', **kwargs):
    """
    :param rev string: Identifies which version of the remote package to download.
                       This could be a commit SHA (git), node id (hg), etc.
    :param zip_url string:
      - Any URL from which a zipfile can be downloaded containing the source code of the
        remote package.
      - Can be a template string using variables {rev} (see :param rev:) and {id}, which
        is the global import identifier of the package, which is specified by the path to
        the BUILD file relative to all 3rd party Go packages (see GoPlatform).
          Example: "https://{id}/archive/{rev}.zip"
      - The zip file is expected to have zipped the package directory itself, and NOT the
        direct contents of the package.
          Expected: `zip -r mylib.zip mylib/`
               Not: `zip -r mylib.zip mylib/*`
    """
    payload = Payload()
    payload.add_fields({
      'rev': PrimitiveField(rev),
      'zip_url': PrimitiveField(zip_url)
    })
    super(GoRemotePackage, self).__init__(payload=payload, **kwargs)
