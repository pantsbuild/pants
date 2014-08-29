# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

"""Static Site Generator for the Pants Build documentation site.

Suggested use:
  cd pants
  ./build-support/bin/publish_docs.sh # invokes docsitegen.py
"""

import os
import sys
import yaml

def load_config(yaml_path):
  config = yaml.load(file(yaml_path).read().decode('utf8'))
  # do some sanity-testing on the config:
  assert(config['tree'][0]['page'] == 'index')
  return config

def main():
  config = load_config(sys.argv[1])

if __name__ == "__main__":
  sys.exit(main())
