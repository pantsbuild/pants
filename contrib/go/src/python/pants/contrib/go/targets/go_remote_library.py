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
      - Can be a template string using variables {host}, {id}, {rev}.
        Example: "{host}/{id}/{rev}.zip"
          - {host} The host address to download zip files from. Specified by an option to
                   GoFetch, '--remote-lib-host'.
          - {id} The global import identifier of the library, which is specified by the path to
                 the BUILD file relative to the source root of all 3rd party Go libraries.
                 For example, If the 3rd party source root is "3rdparty/go", a target at
                 "3rdparty/go/github.com/user/lib" would have an {id} of "github.com/user/lib".
          - {rev} See :param rev:
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
