# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import SourcesField
from pants.base.target import Target


class GenResources(Target):
  RTL = 'rtl'
  LESSC = 'lessc'
  REQUIRE_JS = 'requirejs'

  _VALID_PROCESSORS = frozenset([RTL, LESSC, REQUIRE_JS])

  def __init__(self,
               address=None,
               sources=None,
               preprocessors=None,
               gen_resource_path=None,
               **kwargs):
    """
    :param name: The name of this target, which combined with this
      build file defines the target :class:`pants.base.address.Address`.
    :param sources: A list of filenames representing the resources
      this library provides.
    :param preprocessors: A list of preprocessors tasks
    :param gen_resource_path: The path where the files need to generated.
      [Default] Target base directory
      This is the path where the generated files will be placed in your application bundle.
    """
    if not preprocessors:
      TargetDefinitionException(self, 'gen_resources should have a list of pre-processors. Refer'
                                      ' `resources` go/builddictionary to use raw sources as is.')
    self._preprocessors = set(preprocessors)

    payload = Payload()
    payload.add_fields({
      'sources': SourcesField(sources=self.assert_list(sources),
                              sources_rel_path=address.spec_path),
    })

    super(GenResources, self).__init__(address=address, payload=payload, **kwargs)

    for preprocessor in preprocessors:
      if preprocessor not in GenResources._VALID_PROCESSORS:
        exp_message = ('Pre-processor {preprocessor} not in found.\nDid you mean one of these?'
                       '\n{valid}').format(preprocessor=preprocessor,
                                           valid=GenResources._VALID_PROCESSORS)
        raise TargetDefinitionException(self, exp_message)

    self._processed = set()
    self._gen_resource_path = gen_resource_path or self.target_base

  @property
  def preprocessors(self):
    return self._preprocessors

  @property
  def gen_resource_path(self):
    return self._gen_resource_path

  @property
  def processed(self):
    return self._processed
