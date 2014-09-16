#!/usr/bin/python
# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
import sys

filename = sys.argv[1]

def extract_artifact(line):
  splitline = line.split('%')
  org = re.sub(r'^revision\.[a-z_]+\.', '', splitline[0])
  name = re.sub(r'=.*', '', splitline[1].rstrip())
  return (org, name)

with open(filename) as f:
  base_dir = os.path.dirname(filename)

  content = f.readlines()
  for line in content:
    # For each line get the org and name, make a directory with these
    # and open the publish file.
    artifact = extract_artifact(line)
    (org, name) = artifact

    publish_dir = os.path.join(base_dir, org, name)
    if not os.path.exists(publish_dir):
      os.makedirs(publish_dir)

    with open(os.path.join(publish_dir, 'publish.properties'), 'a') as output:
      output.write(line)
