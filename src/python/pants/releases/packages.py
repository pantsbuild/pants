# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import os
import sys
from builtins import object
from configparser import ConfigParser
from functools import total_ordering

from bs4 import BeautifulSoup
from future.moves.urllib.error import HTTPError
from future.moves.urllib.request import Request, urlopen

from pants.util.process_handler import subprocess


COLOR_BLUE = "\x1b[34m"
COLOR_RESET = "\x1b[0m"


def banner(message):
  print("{}[=== {} ===]{}".format(COLOR_BLUE, message, COLOR_RESET))


@total_ordering
class Package(object):

  def __init__(self, name):
    self.name = name

  def __lt__(self, other):
    return self.name < other.name

  def __eq__(self, other):
    return self.name == other.name

  def __hash__(self):
    return super(Package, self).__hash__()

  def __str__(self):
    return self.name

  def exists(self):
    req = Request("https://pypi.python.org/pypi/{}".format(self.name))
    req.get_method = lambda: "HEAD"
    try:
      urlopen(req)
      return True
    except HTTPError as e:
      if e.code == 404:
        return False
      raise

  def latest_version(self):
    f = urlopen("https://pypi.python.org/pypi/{}/json".format(self.name))
    j = json.load(f)
    return j["info"]["version"]

  def owners(self,
             html_node_type='a',
             html_node_class='sidebar-section__user-gravatar',
             html_node_attr='aria-label'):
    url = "https://pypi.python.org/pypi/{}/{}".format(self.name, self.latest_version())
    url_content = urlopen(url).read()
    parser = BeautifulSoup(url_content, 'html.parser')
    owners = [
      item.attrs[html_node_attr]
      for item
      in parser.find_all(html_node_type, class_=html_node_class)
    ]
    return set(owner.lower() for owner in owners)


core_packages = {
  Package("pantsbuild.pants"),
  Package("pantsbuild.pants.testinfra"),
}


def contrib_packages():
  output = subprocess.check_output(
    ('bash', '-c', 'source contrib/release_packages.sh ; for pkg in "${CONTRIB_PACKAGES[@]}"; do echo "${!pkg}"; done')
  ).decode('utf-8')
  return set(Package(name) for name in output.strip().split('\n'))


def all_packages():
  return core_packages.union(contrib_packages())


def get_pypi_config(section, option):
  config = ConfigParser()
  config.read(os.path.expanduser('~/.pypirc'))

  if not config.has_option(section, option):
    raise ValueError('Your ~/.pypirc must define a {} option in the {} section'.format(option, section))
  return config.get(section, option)


def check_ownership(users, minimum_owner_count=3):
  minimum_owner_count = max(len(users), minimum_owner_count)
  packages = sorted(all_packages())
  banner("Checking package ownership for {} packages".format(len(packages)))
  users = set(user.lower() for user in users)
  insufficient = set()
  unowned = dict()

  def check_ownership(i, package):
    banner("[{}/{}] checking ownership for {}: > {} releasers including {}".format(i, len(packages), package, minimum_owner_count, ", ".join(users)))
    if not package.exists():
      print("The {} package is new! There are no owners yet.".format(package.name))
      return

    owners = package.owners()
    if len(owners) <= minimum_owner_count:
      insufficient.add(package)

    difference = users.difference(owners)
    for d in difference:
      unowned.setdefault(d, set()).add(package)

  for i, package in enumerate(packages):
    check_ownership(i, package)

  if insufficient or unowned:
    if unowned:
      for user, packages in sorted(unowned.items()):
        print("Pypi account {} needs to be added as an owner for the following packages:\n{}".format(user, "\n".join(package.name for package in sorted(packages))), file=sys.stderr)

    if insufficient:
      print('The following packages have fewer than {} owners but should be setup for all releasers:\n{}'.format(minimum_owner_count, '\n'.join(package.name for package in insufficient)))

    sys.exit(1)


if sys.argv[1:] == ["list"]:
  print('\n'.join(package.name for package in sorted(all_packages())))
elif sys.argv[1:] == ["list-owners"]:
  for package in sorted(all_packages()):
    if not package.exists():
      print("The {} package is new!  There are no owners yet.".format(package.name), file=sys.stderr)
      continue
    print("Owners of {}:".format(package.name))
    for owner in sorted(package.owners()):
      print("{}".format(owner))
elif sys.argv[1:] == ["check-my-ownership"]:
  me = get_pypi_config('server-login', 'username')
  check_ownership({me})
else:
  raise Exception("Didn't recognise arguments {}".format(sys.argv[1:]))
