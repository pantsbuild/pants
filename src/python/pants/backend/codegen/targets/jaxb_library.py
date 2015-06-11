# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField


class JaxbLibrary(JvmTarget):
  """Generates a stub Java library from jaxb xsd files."""

  def __init__(self, payload=None, package=None, language='java', **kwargs):
    """
    :param package: java package (com.company.package) in which to generate the output java files.
      If unspecified, Pants guesses it from the file path leading to the schema
      (xsd) file. This guess is accurate only if the .xsd file is in a path like
      ``.../com/company/package/schema.xsd``. Pants looks for packages that start with 'com', 'org',
      or 'net'.
    :param string language: only 'java' is supported. Default: 'java'
    """

    payload = payload or Payload()
    payload.add_fields({
      'package': PrimitiveField(package),
      'jaxb_language': PrimitiveField(language),
    })
    super(JaxbLibrary, self).__init__(payload=payload, **kwargs)

    self.add_labels('codegen')
    self.add_labels('jaxb')

    if language != 'java':
      raise ValueError('Language "{lang}" not supported for {class_type}'
                       .format(lang=language, class_type=type(self).__name__))

  @property
  def package(self):
    return self.payload.package
