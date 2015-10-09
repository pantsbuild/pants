# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.engine.exp.addressable import (Exactly, SubclassesOf, addressable, addressable_dict,
                                          addressable_list)
from pants.engine.exp.configuration import Configuration


# TODO(John Sirois): document as the contract for targets fleshes out; especially the role of
# configurations.
class Target(Configuration):
  # An example of an addressable (is Serializable + has a name) that can cause graph walks.  The
  # only magic here are the fields wrapped with `addressables` which allow for mixed addresses and
  # embedded objects.  The addresses are tagged by being wrapped in the Addressed type which allows
  # a lazy resolution of the addressed and re-construction of this object with the fully resolved
  # properties later.

  def __init__(self, name=None, configurations=None, dependencies=None, **kwargs):
    super(Target, self).__init__(name=name, **kwargs)
    self.configurations = configurations
    self.dependencies = dependencies

  @addressable_list(SubclassesOf(Configuration))
  def configurations(self):
    """"""

  @property
  def dependencies(self):
    """"""

# Since Target.dependencies is recursive on the Target type, we need to post-class-definition
# re-define dependencies in this way.
Target.dependencies = addressable_list(SubclassesOf(Target))(Target.dependencies)


class ApacheThriftConfiguration(Configuration):
  # An example of a mixed-mode object - can be directly embedded without a name or else referenced
  # via address if both top-level and carrying a name.
  #
  # Also an example of a more constrained config object that has an explicit set of allowed fields
  # and that can have pydoc hung directly off the constructor to convey a fully accurate BUILD
  # dictionary entry.

  def __init__(self, name=None, version=None, strict=None, lang=None, options=None, **kwargs):
    super(ApacheThriftConfiguration, self).__init__(name=name,
                                                    version=version,
                                                    strict=strict,
                                                    lang=lang,
                                                    options=options,
                                                    **kwargs)

  # An example of a validatable bit of config.
  def validate_concrete(self):
    if not self.version:
      self.report_validation_error('A thrift `version` is required.')
    if not self.lang:
      self.report_validation_error('A thrift gen `lang` is required.')


class PublishConfiguration(Configuration):
  # An example of addressable and addressable_mapping field wrappers.

  def __init__(self, default_repo, repos, name=None, **kwargs):
    super(PublishConfiguration, self).__init__(name=name, **kwargs)
    self.default_repo = default_repo
    self.repos = repos

  @addressable(Exactly(Configuration))
  def default_repo(self):
    """"""

  @addressable_dict(Exactly(Configuration))
  def repos(self):
    """"""
