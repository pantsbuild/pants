# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from hashlib import sha1

import six
from twitter.common.lang import Compatibility

from pants.base.payload_field import PayloadField, stable_json_sha1
from pants.backend.jvm.repository import Repository


class Artifact(PayloadField):
  """Represents a jvm artifact ala maven or ivy.

  Used in the ``provides`` parameter to *jvm*\_library targets.
  """

  def __init__(self, org, name, repo, description=None):
    """
    :param string org: Organization of this artifact, or groupId in maven parlance.
    :param string name: Name of the artifact, or artifactId in maven parlance.
    :param repo: The ``repo`` this artifact is published to.
    :param string description: Description of this artifact.
    """
    if not isinstance(org, Compatibility.string):
      raise ValueError("org must be %s but was %s" % (Compatibility.string, org))
    if not isinstance(name, Compatibility.string):
      raise ValueError("name must be %s but was %s" % (Compatibility.string, name))
    if not isinstance(repo, Repository):
      raise ValueError("repo must be an instance of Repository")

    if description is not None and not isinstance(description, Compatibility.string):
      raise ValueError("description must be None or %s but was %s"
                       % (Compatibility.string, description))

    self.org = org
    self.name = name
    self.rev = None
    self.repo = repo
    self.description = description

  def __eq__(self, other):
    return (type(other) == Artifact and
            self.org == other.org and
            self.name == other.name)

  def __hash__(self):
    return hash((self.org, self.name))

  def _compute_fingerprint(self):
    return stable_json_sha1((self.org, self.name, self.rev))

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return "%s-%s -> %s" % (self.org, self.name, self.repo)
