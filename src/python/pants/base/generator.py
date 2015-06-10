# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import pprint

import pystache

from pants.base.mustache import MustacheRenderer


class TemplateData(dict):
  """Encapsulates data for a mustache template as a property-addressable read-only map-like struct.
  """

  def __init__(self, **kwargs):
    dict.__init__(self, MustacheRenderer.expand(kwargs))

  def extend(self, **kwargs):
    """Returns a new TemplateData with this template's data overlayed by the key value pairs
    specified as keyword arguments."""

    props = self.copy()
    props.update(kwargs)
    return TemplateData(**props)

  def __setattr__(self, key, value):
    raise AttributeError("Mutation not allowed - use {}.extend({} = {})".format(self, key, value))

  def __getattr__(self, key):
    if key in self:
      return self[key]
    else:
      return object.__getattribute__(self, key)

  def __str__(self):
    return 'TemplateData({})'.format(pprint.pformat(self))


class Generator(object):
  """Generates pants intermediary output files using a configured mustache template."""

  def __init__(self, template_text, **template_data):
    self._template = MustacheRenderer.parse_template(template_text)
    self.template_data = template_data

  def render(self):
    """Applies the template to the template data and returns the output."""
    return pystache.render(self._template, self.template_data)

  def write(self, stream):
    """Applies the template to the template data and writes the result to the given file-like
    stream."""

    stream.write(self.render())
