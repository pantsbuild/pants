# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import pprint

import pystache

from pants.base.mustache import MustacheRenderer


# TODO(benjy): Get rid of this class? It just adds complexity, and a regular dict should be fine.
# Unfortunately we first have to fix external uses of this should-be-internal-only class.
class TemplateData(dict):
  """Encapsulates mustache template arguments as a property-addressable read-only object."""

  def __init__(self, **kwargs):
    super(TemplateData, self).__init__(MustacheRenderer.expand(kwargs))

  def extend(self, **kwargs):
    """Returns a new instance with this instance's data overlayed by the key-value args."""

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


# TODO(benjy): Get rid of this class? It adds basically nothing over the MustacheRenderer.
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
