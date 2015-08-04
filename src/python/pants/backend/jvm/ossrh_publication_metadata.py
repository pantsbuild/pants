# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import six

from pants.backend.jvm.artifact import PublicationMetadata
from pants.base.validation import assert_list


def _validate_maybe_string(name, item):
  if item and not isinstance(item, six.string_types):
    raise ValueError('{} was expected to be of type {} but given {}'.format(name, type(item), item))
  return item


def _validate_string(name, item):
  if not item:
    raise ValueError('{} is a required field'.format(name))
  return _validate_maybe_string(name, item)


class Scm(object):
  """Corresponds to the maven POM <scm/> element.

  Refer to the schema here: http://maven.apache.org/maven-v4_0_0.xsd
  """

  @classmethod
  def github(cls, user, repo):
    """Creates an `Scm` for a github repo.

    :param string user: The github user or organization name the repo is hosted under.
    :param string repo: The repository name.
    :returns: An `Scm` representing the github repo.
    """
    # For the url format, see: http://maven.apache.org/scm/git.html
    params = dict(user=user, repo=repo)
    connection = 'scm:git:git@github.com:{user}/{repo}.git'.format(**params)
    url = 'https://github.com/{user}/{repo}'.format(**params)
    return cls(connection=connection, developer_connection=connection, url=url)

  def __init__(self, connection, developer_connection, url, tag=None):
    """See http://maven.apache.org/scm/scms-overview.html for valid connection formats for your scm.

    :param string connection: The scm connection string for read-only access to the scm.
    :param string developer_connection: The scm connection string for read-write access to the scm.
    :param string url: An url pointing to a browseable web interface for the scm.
    :param string tag: An optional tag corresponding to the published release.  This will be
                       populated by pants during publish runs.
    """
    self.connection = _validate_string('connection', connection)
    self.developer_connection = _validate_string('developer_connection', developer_connection)
    self.url = _validate_string('url', url)
    self.tag = _validate_maybe_string('tag', tag)

  def tagged(self, tag):
    """Creates a new `Scm` identical to this `Scm` but with the given `tag`."""
    return Scm(self.connection, self.developer_connection, self.url, tag=tag)


class License(object):
  """Corresponds to the maven POM <license/> element.

  Refer to the schema here: http://maven.apache.org/maven-v4_0_0.xsd
  """

  def __init__(self, name, url, comments=None):
    """
    :param string name: The full official name of the license.
    :param string url: An url pointing to the license text.
    :param string comments: Optional comments clarifying the license.
    """
    self.name = _validate_string('name', name)
    self.url = _validate_string('url', url)
    self.comments = _validate_maybe_string('comments', comments)


class Developer(object):
  """Corresponds to the maven POM <developer/> element.

  Refer to the schema here: http://maven.apache.org/maven-v4_0_0.xsd
  """

  def __init__(self, user_id=None, name=None, email=None, url=None, organization=None,
               organization_url=None, roles=None):
    """One of `user_id`, `name`, or `email` is required, all other parameters are optional.

    :param string user_id: The user id of the developer; typically the one used to access the scm.
    :param string name: The developer's full name.
    :param string email: the developer's email address.
    :param string url: An optional url pointing to more information about the developer.
    :param string organization: An optional name for the organization the developer works on the
                                library for.
    :param string organization_url: An optional url pointing to more information about the
                                    developer's organization.
    :param list roles: An optional list of role names that apply to this developer on this project.
    """
    if not (user_id or name or email):
      raise ValueError("At least one of 'user_id', 'name' or 'email' must be specified for each "
                       "developer.")
    self.user_id = _validate_maybe_string('user_id', user_id)
    self.name = _validate_maybe_string('name', name)
    self.email = _validate_maybe_string('email', email)
    self.url = _validate_maybe_string('url', url)
    self.organization = _validate_maybe_string('organization', organization)
    self.organization_url = _validate_maybe_string('organization_url', organization_url)
    self.roles = assert_list(roles, key_arg='roles')

  @property
  def has_roles(self):
    """Returns `True` if this developer has one or more roles."""
    # TODO(John Sirois): This is a layer leak - it only supports mustache rendering.
    # Consider converting the OSSRHPublicationMetadata tree to a suitable form for mustache
    # rendering where the rendering occurs (currently just in the JarPublish task).
    return bool(self.roles)


class OSSRHPublicationMetadata(PublicationMetadata):
  """Corresponds to the Sonatype required fields for jars published to OSSRH.

  See: http://central.sonatype.org/pages/requirements.html#sufficient-metadata
  """

  def __init__(self, description, url, licenses, developers, scm, name=None):
    """All parameters are required except for `name` to pass OSSRH requirements.

    :param string description: A description of the library.
    :param string url: An url pointing to more information about the library.
    :param list licenses: The licenses that apply to the library.
    :param list developers:  The developers who work on the library.
    :param scm: The primary scm system hosting the library source code.
    :param string name: The optional full name of the library.  If not supplied an appropriate name
                        will be synthesized.
    """
    def validate_nonempty_list(list_name, item, expected_type):
      assert_list(item, expected_type=expected_type, can_be_none=False, key_arg='roles', allowable=(list,))
      if not item:
        raise ValueError('At least 1 entry is required in the {} list.'.format(list_name))
      return item

    self.description = _validate_string('description', description)
    self.url = _validate_string('url', url)
    self.licenses = validate_nonempty_list('licenses', licenses, License)
    self.developers = validate_nonempty_list('developers', developers, Developer)

    if not isinstance(scm, Scm):
      raise ValueError("scm must be an instance of Scm")
    self.scm = scm

    self.name = _validate_maybe_string('name', name)

  def _compute_fingerprint(self):
    # TODO(John Sirois): Untangle a JvmTarget's default fingerprint from the `provides` payload
    # fingerprint.  Only the JarPublish task would be a consumer for this and today it rolls its
    # own hash besides.  For now just short-circuit the fingerprint, but after untangling, consider
    # implementing a fingerprint consistent with the need to re-publish to maven central.
    return None
