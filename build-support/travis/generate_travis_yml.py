# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import pkg_resources
import pystache


def generate_travis_yml():
  template = pkg_resources.resource_string(__name__, 'travis.yml.mustache').decode('utf-8')
  context = {'integration_shards': range(0, 7)}
  print(pystache.render(template, context))

