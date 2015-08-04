# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.base.target import Target


class GoRemoteLibrary(Target):

  def __init__(self, zip_url, rev='', **kwargs):
    """
    :param str zip_url:
      - Any URL from which a zipfile can be downloaded containing the source code of the
        remote library.
      - Can be a template string using variables {rev} (see :param rev:) and {id}, which
        is the global import identifier of the library, which is specified by the path to
        the BUILD file relative to all 3rd party Go libraries (see GoPlatform).
          Example: "https://{id}/archive/{rev}.zip"
      - The zip file is expected to have zipped the library directory itself, and NOT the
        direct contents of the library.
          Expected: `zip -r mylib.zip mylib/`
               Not: `zip -r mylib.zip mylib/*`
    :param str rev: Identifies which version of the remote library to download.
                    This could be a commit SHA (git), node id (hg), etc.
    """
    payload = Payload()
    payload.add_fields({
      'rev': PrimitiveField(rev),
      'zip_url': PrimitiveField(zip_url)
    })
    super(GoRemoteLibrary, self).__init__(payload=payload, **kwargs)
