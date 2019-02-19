# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import pkg_resources
import pystache


num_py3_integration_shards = 19
num_py2_blacklist_integration_shards = 1
num_cron_integration_shards = 20


HEADER = """
# GENERATED, DO NOT EDIT!
# To change, edit build-support/travis/travis.yml.mustache and run
# ./pants --quiet run build-support/travis:generate_travis_yml > .travis.yml
#
# Tip: Copy the generated `.travis.yml` into https://yamlvalidator.com to validate the YAML
# and see how the entries resolve to normalized JSON (helpful to debug anchors).
"""


def generate_travis_yml():
  """Generates content for a .travis.yml file from templates."""
  def get_mustache_file(file_name):
    return pkg_resources.resource_string(__name__, file_name).decode('utf-8')

  template = get_mustache_file('travis.yml.mustache')
  before_install_linux = get_mustache_file('before_install_linux.mustache')
  before_install_osx = get_mustache_file('before_install_osx.mustache')
  env_osx_with_pyenv = get_mustache_file('env_osx_with_pyenv.mustache')

  context = {
    'header': HEADER,
    'py3_integration_shards': range(0, num_py3_integration_shards),
    'py3_integration_shards_length': num_py3_integration_shards,
    'py2_blacklist_integration_shards': range(0, num_py2_blacklist_integration_shards),
    'py2_blacklist_integration_shards_length': num_py2_blacklist_integration_shards,
    'cron_integration_shards': range(0, num_cron_integration_shards),
    'cron_integration_shards_length': num_cron_integration_shards,
  }
  renderer = pystache.Renderer(partials={
    'before_install_linux': before_install_linux,
    'before_install_osx': before_install_osx,
    'env_osx_with_pyenv': env_osx_with_pyenv
  })
  print(renderer.render(template, context))
