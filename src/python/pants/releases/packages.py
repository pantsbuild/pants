# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import argparse
import json
import os
import sys
from builtins import object
from collections import defaultdict
from configparser import ConfigParser
from distutils.util import get_platform
from functools import total_ordering

from bs4 import BeautifulSoup
from future.moves.urllib.error import HTTPError
from future.moves.urllib.request import Request, urlopen
from future.utils import PY2

if PY2:
  import subprocess32 as subprocess
else:
  import subprocess

COLOR_BLUE = "\x1b[34m"
COLOR_RESET = "\x1b[0m"


def banner(message):
  print("{}[=== {} ===]{}".format(COLOR_BLUE, message, COLOR_RESET))


@total_ordering
class Package(object):

  def __init__(self, name, target, bdist_wheel_flags=None):
    self.name = name
    self.target = target
    self.bdist_wheel_flags = bdist_wheel_flags or ("--python-tag", "py27.py36.py37")

  def __lt__(self, other):
    return self.name < other.name

  def __eq__(self, other):
    return self.name == other.name

  def __hash__(self):
    return super(Package, self).__hash__()

  def __str__(self):
    return self.name

  def __repr__(self):
    return "Package<name={}>".format(self.name)

  def exists(self):
    req = Request("https://pypi.org/pypi/{}".format(self.name))
    req.get_method = lambda: "HEAD"
    try:
      urlopen(req)
      return True
    except HTTPError as e:
      if e.code == 404:
        return False
      raise

  def latest_version(self):
    f = urlopen("https://pypi.org/pypi/{}/json".format(self.name))
    j = json.load(f)
    return j["info"]["version"]

  def owners(self,
             html_node_type='a',
             html_node_class='sidebar-section__user-gravatar',
             html_node_attr='aria-label'):
    url = "https://pypi.org/pypi/{}/{}".format(self.name, self.latest_version())
    url_content = urlopen(url).read()
    parser = BeautifulSoup(url_content, 'html.parser')
    owners = [
      item.attrs[html_node_attr]
      for item
      in parser.find_all(html_node_type, class_=html_node_class)
    ]
    return {owner.lower() for owner in owners}


def find_platform_name():
  # See: https://www.python.org/dev/peps/pep-0425/#id13
  return get_platform().replace("-", "_").replace(".", "_")


def core_packages(py2):
  # N.B. When releasing with Python 3, we constrain the ABI (Application Binary Interface) to cp36 to allow
  # pantsbuild.pants to work with any Python 3 version>= 3.6. We are able to get this future compatibility by
  # specifing `abi3`, which signifies any version >= 3.6 must work. This is possible to set because in
  # `src/rust/engine/src/cffi/native_engine.c` we set up `Py_LIMITED_API` and in `src/python/pants/BUILD` we
  # set ext_modules, which together allows us to mark the abi tag. See https://docs.python.org/3/c-api/stable.html
  # for documentation and https://bitbucket.org/pypa/wheel/commits/1f63b534d74b00e8c2e8809f07914f6da4502490?at=default#Ldocs/index.rstT121
  # for how to mark the ABI through bdist_wheel.
  bdist_wheel_flags = ("--py-limited-api", "cp36") if not py2 else ("--python-tag", "cp27", "--plat-name", find_platform_name())
  return {
    Package("pantsbuild.pants", "//src/python/pants:pants-packaged", bdist_wheel_flags=bdist_wheel_flags),
    Package("pantsbuild.pants.testinfra", "//tests/python/pants_test:test_infra"),
  }


def contrib_packages():
  return {
    Package(
      "pantsbuild.pants.contrib.scrooge",
      "//contrib/scrooge/src/python/pants/contrib/scrooge:plugin",
    ),
    Package(
      "pantsbuild.pants.contrib.buildgen",
      "//contrib/buildgen/src/python/pants/contrib/buildgen:plugin",
    ),
    Package(
      "pantsbuild.pants.contrib.go",
      "//contrib/go/src/python/pants/contrib/go:plugin",
    ),
    Package(
      "pantsbuild.pants.contrib.node",
      "//contrib/node/src/python/pants/contrib/node:plugin",
    ),
    Package(
      "pantsbuild.pants.contrib.scalajs",
      "//contrib/scalajs/src/python/pants/contrib/scalajs:plugin",
    ),
    Package(
      "pantsbuild.pants.contrib.python.checks",
      "//contrib/python/src/python/pants/contrib/python/checks:plugin",
    ),
    Package(
      "pantsbuild.pants.contrib.python.checks.checker",
      "//contrib/python/src/python/pants/contrib/python/checks/checker",
      bdist_wheel_flags=("--universal",),
    ),
    Package(
      "pantsbuild.pants.contrib.findbugs",
      "//contrib/findbugs/src/python/pants/contrib/findbugs:plugin",
    ),
    Package(
      "pantsbuild.pants.contrib.cpp",
      "//contrib/cpp/src/python/pants/contrib/cpp:plugin",
    ),
    Package(
      "pantsbuild.pants.contrib.confluence",
      "//contrib/confluence/src/python/pants/contrib/confluence:plugin",
    ),
    Package(
      "pantsbuild.pants.contrib.errorprone",
      "//contrib/errorprone/src/python/pants/contrib/errorprone:plugin",
    ),
    Package(
      "pantsbuild.pants.contrib.codeanalysis",
      "//contrib/codeanalysis/src/python/pants/contrib/codeanalysis:plugin",
    ),
    Package(
      "pantsbuild.pants.contrib.jax_ws",
      "//contrib/jax_ws/src/python/pants/contrib/jax_ws:plugin",
    ),
    Package(
      "pantsbuild.pants.contrib.mypy",
      "//contrib/mypy/src/python/pants/contrib/mypy:plugin",
    ),
    Package(
      "pantsbuild.pants.contrib.avro",
      "//contrib/avro/src/python/pants/contrib/avro:plugin",
    ),
    Package(
      "pantsbuild.pants.contrib.thrifty",
      "//contrib/thrifty/src/python/pants/contrib/thrifty:plugin",
    ),
    Package(
      "pantsbuild.pants.contrib.googlejavaformat",
      "//contrib/googlejavaformat/src/python/pants/contrib/googlejavaformat:plugin",
    ),
    Package(
      "pantsbuild.pants.contrib.awslambda_python",
      "//contrib/awslambda/python/src/python/pants/contrib/awslambda/python:plugin",
    ),
  }


def all_packages(py2):
  return core_packages(py2).union(contrib_packages())


def build_and_print_packages(version, py2=False):
  packages_by_flags = defaultdict(list)
  for package in sorted(all_packages(py2)):
    packages_by_flags[package.bdist_wheel_flags].append(package)

  for (flags, packages) in packages_by_flags.items():
    args = ("./pants", "setup-py", "--run=bdist_wheel {}".format(" ".join(flags))) + tuple(package.target for package in packages)
    try:
      subprocess.check_call(args, stdout=sys.stderr)
      for package in packages:
        print(package.name)
    except subprocess.CalledProcessError:
      print("Failed to build packages {names} for {version} with targets {targets}".format(
        names=','.join(package.name for package in packages),
        version=version,
        targets=' '.join(package.target for package in packages),
      ), file=sys.stderr)
      raise


def get_pypi_config(section, option):
  config = ConfigParser()
  config.read(os.path.expanduser('~/.pypirc'))

  if not config.has_option(section, option):
    raise ValueError('Your ~/.pypirc must define a {} option in the {} section'.format(option, section))
  return config.get(section, option)


def check_ownership(users, minimum_owner_count=3, py2=False):
  minimum_owner_count = max(len(users), minimum_owner_count)
  packages = sorted(all_packages(py2))
  banner("Checking package ownership for {} packages".format(len(packages)))
  users = {user.lower() for user in users}
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


def _create_parser():
  parser = argparse.ArgumentParser()
  # Note because of how argparse handles subparsers, the --py2 flag must be passed before any of the subparser
  # flags to resolve properly.
  parser.add_argument("-2", "--py2", action="store_true", default=False, help="Release any non-universal packages as Python 2.")
  subparsers = parser.add_subparsers(dest="command")
  # list
  parser_list = subparsers.add_parser('list')
  parser_list.add_argument("--with-packages", action="store_true")
  # list-owners
  subparsers.add_parser("list-owners")
  # check-my-ownership
  subparsers.add_parser("check-my-ownership")
  # build_and_print
  parser_build_and_print = subparsers.add_parser("build_and_print")
  parser_build_and_print.add_argument("version")
  return parser


args = _create_parser().parse_args()

if args.command == "list":
  if args.with_packages:
    print('\n'.join(
      '{} {} {}'.format(package.name, package.target, " ".join(package.bdist_wheel_flags))
      for package in sorted(all_packages(args.py2))))
  else:
    print('\n'.join(package.name for package in sorted(all_packages(args.py2))))
elif args.command == "list-owners":
  for package in sorted(all_packages(args.py2)):
    if not package.exists():
      print("The {} package is new!  There are no owners yet.".format(package.name), file=sys.stderr)
      continue
    print("Owners of {}:".format(package.name))
    for owner in sorted(package.owners()):
      print("{}".format(owner))
elif args.command == "check-my-ownership":
  me = get_pypi_config('server-login', 'username')
  check_ownership({me}, py2=args.py2)
elif args.command == "build_and_print":
  build_and_print_packages(args.version, py2=args.py2)
else:
  raise argparse.ArgumentError("Didn't recognise arguments {}".format(args))
