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
  """Defines sources with transpilers to run on these sources."""
  LESS = 'less'
  R2 = 'R2'
  REQUIRE_JS = 'requirejs'

  _VALID_TRANSPILERS = frozenset([R2, LESS, REQUIRE_JS])
  _TRANSPILERS_DESC = ['less: Less is a CSS pre-processor.',
                       'R2: A CSS LTR to RTL converter',
                       'requirejs: RequireJS is a JavaScript file and module loader.']

  def __init__(self,
               address=None,
               sources=None,
               transpilers=None,
               gen_resource_path=None,
               **kwargs):
    """
    :param name: The name of this target, which combined with this
      build file defines the target :class:`pants.base.address.Address`.
    :param sources: A list of filenames representing the resources
      this library provides.
    :param transpilers: A list of transpilers tasks
    :param gen_resource_path: The path where the files need to generated.
      [Default] Target base directory
      This is the path where the generated files will be placed in your application bundle.
    """
    payload = Payload()
    payload.add_fields({
      'sources': SourcesField(sources=self.assert_list(sources),
                              sources_rel_path=address.spec_path),
      })
    super(GenResources, self).__init__(address=address, payload=payload, **kwargs)

    if not transpilers:
      raise TargetDefinitionException(self, 'gen_resources should have a list of transpilers.'
        'We currently support transpilers {0}'.format('\n'.join(GenResources._TRANSPILERS_DESC)))

    self._transpilers = set(transpilers)

    for transpiler in transpilers:
      if transpiler not in GenResources._VALID_TRANSPILERS:
        exp_message = ('Transpiler {transpiler} not in found.\nDid you mean one of these?'
                       '\n{valid}').format(transpiler=transpiler,
                                           valid='\n'.join(GenResources._TRANSPILERS_DESC))
        raise TargetDefinitionException(self, exp_message)

    self._gen_resource_path = gen_resource_path or self.target_base

  @property
  def transpilers(self):
    return self._transpilers

  @property
  def gen_resource_path(self):
    return self._gen_resource_path
