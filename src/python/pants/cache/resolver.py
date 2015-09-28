# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import logging
from abc import abstractmethod

import requests

from pants.base.validation import assert_list
from pants.util.meta import AbstractClass


logger = logging.getLogger(__name__)


class Resolver(AbstractClass):
  """An abstract class base for resolving service urls."""

  class ResolverError(Exception):
    """Indicate an error resolving service urls."""

  @abstractmethod
  def resolve(self, resolve_from):
    """Query resolve_from for a list of service urls.

    :param resolve_from: The discovery endpoint that may be on different protocols.
    :return: A non-empty list of URLs. URL is the same format as remote artifact cache.
    :rtype: list of strings
    :raises :class:`Resolver.ResolverError` if there is an error resolving service urls.
    """


class NoopResolver(Resolver):
  """A resolver that always yields nothing"""

  def resolve(self, resolve_from):
    return []


class ResponseParser(object):
  """Resolver response parser utility class."""

  class ResponseParserError(Exception):
    """Indicates an error parsing response from resolver."""

  def __init__(self, format='json_map', encoding='utf-8', index='hostlist'):
    self.format = format
    self.encoding = encoding
    self.index = index

  def parse(self, content):
    """Parse raw response content for a list of remote artifact cache URLs."""
    if self.format == 'json_map':
      try:
        return assert_list(json.loads(content.decode(self.encoding))[self.index])
      except (KeyError, UnicodeDecodeError, ValueError) as e:
        raise self.ResponseParserError("Error while parsing response content: {0}".format(str(e)))

    # Should never get here.
    raise ValueError('Unknown content format: "{}"'.format(self.format))


class RESTfulResolver(Resolver):
  """Query a resolver on RESTful interface."""

  def __init__(self, timeout, tries, response_parser=None):
    """
    :param int timeout: Timeout for GET in seconds.
    :param int tries: Max number of retries. See docstring on `requests.adapters.HTTPAdapter`
                      for details.
    :param response_parser: Parser to extract the resolved URLS from response.
    """
    self._timeout = timeout
    self._tries = tries
    self._response_parser = response_parser or ResponseParser()

  def _safe_get_content(self, session, resolve_from):
    try:
      resp = session.get(resolve_from, timeout=self._timeout)
      if resp.status_code == requests.codes.ok:
        return resp.content
      raise self.ResolverError('Error status_code={0}'.format(resp.status_code))
    except requests.RequestException as e:
      raise self.ResolverError('Request error from {0}'.format(resolve_from))

  def resolve(self, resolve_from):
    session = requests.Session()
    session.mount(resolve_from, requests.adapters.HTTPAdapter(max_retries=self._tries))
    content = self._safe_get_content(session, resolve_from)
    try:
      parsed_urls = self._response_parser.parse(content)
      if len(parsed_urls) > 0:
        return parsed_urls
      raise self.ResolverError('Empty result received from {0}'.format(resolve_from))
    except ResponseParser.ResponseParserError as e:
      raise self.ResolverError('Error parsing response: {0}'.format(str(e)))
