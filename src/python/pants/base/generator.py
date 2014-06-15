# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import pprint

import pystache
from twitter.common.lang import Compatibility

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
    raise AttributeError("Mutation not allowed - use %s.extend(%s = %s)" % (self, key, value))

  def __getattr__(self, key):
    if key in self:
      return self[key]
    else:
      return object.__getattribute__(self, key)

  def __str__(self):
    return 'TemplateData(%s)' % pprint.pformat(self)


class Generator(object):
  """Generates pants intermediary output files using a configured mustache template."""

  def __init__(self, template_text, **template_data):
    # pystache does a typecheck for unicode in python 2.x but rewrites its sources to deal unicode
    # via str in python 3.x.
    if Compatibility.PY2:
      template_text = unicode(template_text)
    self._template = pystache.parse(template_text)
    self.template_data = template_data

  def write(self, stream):
    """Applies the template to the template data and writes the result to the given file-like
    stream."""

    stream.write(pystache.render(self._template, self.template_data))
