# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from six import string_types

from pants.backend.jvm.repository import Repository
from pants.base.payload_field import PayloadField, stable_json_sha1


class PublicationMetadata(PayloadField):
  """Extra metadata required to publish an artifact beyond its coordinates."""


class Artifact(PayloadField):
  """Represents a publishable jvm artifact ala maven or ivy.

  Used in the ``provides`` parameter to *jvm*\_library targets.
  """

  def __init__(self, org, name, repo, publication_metadata=None):
    """
    :param string org: Organization of this artifact, or groupId in maven parlance.
    :param string name: Name of the artifact, or artifactId in maven parlance.
    :param repo: The ``repo`` this artifact is published to.
    :param publication_metadata: Optional extra publication metadata required by the ``repo``.
    """
    if not isinstance(org, string_types):
      raise ValueError("org must be {} but was {}".format(string_types, org))
    if not isinstance(name, string_types):
      raise ValueError("name must be {} but was {}".format(string_types, name))
    if not isinstance(repo, Repository):
      raise ValueError("repo must be an instance of Repository")

    if (publication_metadata is not None
        and not isinstance(publication_metadata, PublicationMetadata)):
      raise ValueError("publication_metadata must be a {} but was a {}"
                       .format(PublicationMetadata, type(publication_metadata)))

    self.org = org
    self._base_name = name
    self.repo = repo
    self.publication_metadata = publication_metadata

  @property
  def name(self):
    return self._base_name

  @name.setter
  def name(self, value):
    self._base_name = value

  def __eq__(self, other):
    return (type(other) == Artifact and
            self.org == other.org and
            self.name == other.name)

  def __hash__(self):
    return hash((self.org, self.name))

  def _compute_fingerprint(self):
    data = (self.org, self.name)

    # NB: The None occupies the legacy rev 3rd slot.  The rev was never populated and always None,
    # so maintaining the slot and its value just serve to preserve the fingerprint and thus
    # containing targets in caches out in the world.
    data += (None,)

    if self.publication_metadata:
      fingerprint = self.publication_metadata.fingerprint()
      if fingerprint:
        data += (fingerprint,)
    return stable_json_sha1(data)

  def __ne__(self, other):
    return not self.__eq__(other)

  def __repr__(self):
    return "{}-{} -> {}".format(self.org, self.name, self.repo)
