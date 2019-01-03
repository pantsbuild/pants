# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import pkg_resources
import pystache


num_integration_shards = 20


HEADER = """
# GENERATED, DO NOT EDIT!
# To change, edit build-support/travis/travis.yml.mustache and run
# ./pants --quiet run build-support/travis:generate_travis_yml > .travis.yml
"""

def generate_travis_yml():
  """Generates content for a .travis.yml file from templates."""
  template = pkg_resources.resource_string(__name__,
                                           'travis.yml.mustache').decode('utf-8')
  before_install = pkg_resources.resource_string(__name__,
                                                 'before_install.mustache').decode('utf-8')
  context = {
    'header': HEADER,
    'integration_shards': range(0, num_integration_shards),
    'integration_shards_length': num_integration_shards,
  }
  renderer = pystache.Renderer(partials={'before_install': before_install})
  print(renderer.render(template, context))
