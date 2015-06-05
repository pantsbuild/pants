#!/usr/bin/python
# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


import os
import re
import sys


if len(sys.argv) != 3:
  print("Usage: publish_migration.py <publish.properties> <directory to write new files>")
  exit(1)

filename = sys.argv[1]
new_base_dir = sys.argv[2]

def extract_artifact(line):
  splitline = line.split('%')
  org = re.sub(r'^revision\.[a-z_]+\.', '', splitline[0])
  name = re.sub(r'=.*', '', splitline[1].rstrip())
  return (org, name)

with open(filename) as f:

  content = f.readlines()
  for line in content:
    # For each line get the org and name, make a directory with these
    # and open the publish file.
    artifact = extract_artifact(line)
    (org, name) = artifact

    publish_dir = os.path.join(new_base_dir, org, name)
    if not os.path.exists(publish_dir):
      os.makedirs(publish_dir)

    with open(os.path.join(publish_dir, 'publish.properties'), 'a') as output:
      output.write(line)
