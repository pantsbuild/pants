# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import pkgutil

import pystache
import six


class MustacheRenderer(object):
  """Renders text using mustache templates."""

  class MustacheError(Exception):
    """Indicates failure rendering mustache templates."""

  @staticmethod
  def expand(args):
    # Add foo? for each foo in the map that evaluates to true.
    # Mustache needs this, especially in cases where foo is a list: there is no way to render a
    # block exactly once iff a list is not empty.
    # Note: if the original map contains foo?, it will take precedence over our synthetic foo?.
    def convert_val(x):
      # Pystache can't handle sets, so we convert to maps of key->True.
      if isinstance(x, set):
        return dict([(k, True) for k in x])
      elif isinstance(x, dict):
        return MustacheRenderer.expand(x)
      elif isinstance(x, list):
        return [convert_val(e) for e in x]
      else:
        return x
    items = [(key, convert_val(val)) for (key, val) in args.items()]
    ret = dict([(key + '?', True) for (key, val) in items if val and not key.endswith('?')])
    ret.update(dict(items))
    return ret

  @staticmethod
  def parse_template(template_text):
    template_text = six.text_type(template_text)
    template = pystache.parse(template_text)
    return template

  def __init__(self, template_dir=None, package_name=None):
    """Create a renderer that finds templates by name in one of two ways.

    * If template_dir is specified, finds template foo in the file foo.mustache in that dir.
    * Otherwise, if package_name is specified, finds template foo embedded in that
      package under templates/foo.mustache.
    * Otherwise will not find templates by name, so can only be used with an existing
      template string.
    """
    self._template_dir = template_dir
    self._package_name = package_name
    self._pystache_renderer = pystache.Renderer(search_dirs=template_dir)
    self._templates = {}

  def render_name(self, template_name, args):
    parsed_template = self._load_template(template_name)
    return self.render(parsed_template, args)

  def render(self, template, args):
    return self._pystache_renderer.render(template, MustacheRenderer.expand(args))

  def _load_template(self, template_name):
    template = self._templates.get(template_name)
    if not template:
      if self._template_dir:
        # Let pystache find the template by name.
        template = self._pystache_renderer.load_template(template_name)
      else:
        # Load the named template embedded in our package.
        path = os.path.join('templates', template_name + '.mustache')
        template_text = pkgutil.get_data(self._package_name, path)
        if template_text is None:
          raise self.MustacheError(
            "could not find template {} in package {}".format(path, self._package_name))
        template = MustacheRenderer.parse_template(template_text)
      self._templates[template_name] = template
    return template
