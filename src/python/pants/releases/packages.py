# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from configparser import ConfigParser
from functools import total_ordering
from typing import Dict, Optional, Set, Tuple, cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

COLOR_BLUE = "\x1b[34m"
COLOR_RESET = "\x1b[0m"


def banner(message: str) -> None:
    print(f"{COLOR_BLUE}[=== {message} ===]{COLOR_RESET}")


@total_ordering
class Package:
    def __init__(
        self, name: str, target: str, bdist_wheel_flags: Optional[Tuple[str, ...]] = None
    ) -> None:
        self.name = name
        self.target = target
        self.bdist_wheel_flags = bdist_wheel_flags or ("--python-tag", "py36.py37.py38")

    def __lt__(self, other):
        return self.name < other.name

    def __eq__(self, other):
        return self.name == other.name

    def __hash__(self):
        return super().__hash__()

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"Package<name={self.name}>"

    def exists(self) -> bool:
        req = Request(f"https://pypi.org/pypi/{self.name}")
        req.get_method = lambda: "HEAD"  # type: ignore[assignment]
        try:
            urlopen(req)
            return True
        except HTTPError as e:
            if e.code == 404:
                return False
            raise

    def latest_version(self) -> str:
        f = urlopen(f"https://pypi.org/pypi/{self.name}/json")
        j = json.load(f)
        return cast(str, j["info"]["version"])

    def owners(self) -> Set[str]:
        url = f"https://pypi.org/pypi/{self.name}/{self.latest_version()}"
        url_content = urlopen(url).read()
        parser = BeautifulSoup(url_content, "html.parser")
        owners = {
            span.find("a", recursive=False).get_text().strip().lower()
            for span in parser.find_all("span", class_="sidebar-section__maintainer")
        }
        return owners


def core_packages() -> Set[Package]:
    # N.B. We constrain the ABI (Application Binary Interface) to cp36 to allow pantsbuild.pants to
    # work with any Python 3 version>= 3.6. We are able to get this future compatibility by specifying
    # `abi3`, which signifies any version >= 3.6 must work. This is possible to set because in
    # `src/rust/engine/src/cffi/native_engine.c` we set up `Py_LIMITED_API` and in `src/python/pants/BUILD` we
    # set ext_modules, which together allows us to mark the abi tag. See https://docs.python.org/3/c-api/stable.html
    # for documentation and https://bitbucket.org/pypa/wheel/commits/1f63b534d74b00e8c2e8809f07914f6da4502490?at=default#Ldocs/index.rstT121
    # for how to mark the ABI through bdist_wheel.
    bdist_wheel_flags = ("--py-limited-api", "cp36")
    return {
        Package(
            "pantsbuild.pants",
            "//src/python/pants:pants-packaged",
            bdist_wheel_flags=bdist_wheel_flags,
        ),
        Package("pantsbuild.pants.testutil", "//src/python/pants/testutil:testutil_wheel"),
    }


def contrib_packages() -> Set[Package]:
    return {
        Package(
            "pantsbuild.pants.contrib.scrooge",
            "//contrib/scrooge/src/python/pants/contrib/scrooge:plugin",
        ),
        Package("pantsbuild.pants.contrib.go", "//contrib/go/src/python/pants/contrib/go:plugin",),
        Package(
            "pantsbuild.pants.contrib.node", "//contrib/node/src/python/pants/contrib/node:plugin",
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
            "pantsbuild.pants.contrib.confluence",
            "//contrib/confluence/src/python/pants/contrib/confluence:plugin",
        ),
        Package(
            "pantsbuild.pants.contrib.codeanalysis",
            "//contrib/codeanalysis/src/python/pants/contrib/codeanalysis:plugin",
        ),
        Package(
            "pantsbuild.pants.contrib.mypy", "//contrib/mypy/src/python/pants/contrib/mypy:plugin",
        ),
        Package(
            "pantsbuild.pants.contrib.awslambda_python",
            "//contrib/awslambda/python/src/python/pants/contrib/awslambda/python:plugin",
        ),
    }


def all_packages() -> Set[Package]:
    return core_packages().union(contrib_packages())


def build_and_print_packages(version: str) -> None:
    packages_by_flags = defaultdict(list)
    for package in sorted(all_packages()):
        packages_by_flags[package.bdist_wheel_flags].append(package)

    for flags, packages in packages_by_flags.items():
        bdist_flags = " ".join(flags)
        args = (
            "./pants",
            "setup-py",
            f"--run=bdist_wheel {bdist_flags}",
            *(package.target for package in packages),
        )
        try:
            # We print stdout to stderr because release.sh is expecting stdout to only be package names.
            subprocess.run(args, stdout=sys.stderr, check=True)
            for package in packages:
                print(package.name)
        except subprocess.CalledProcessError:
            failed_packages = ",".join(package.name for package in packages)
            failed_targets = " ".join(package.target for package in packages)
            print(
                f"Failed to build packages {failed_packages} for {version} with targets "
                f"{failed_targets}",
                file=sys.stderr,
            )
            raise


def get_pypi_config(section: str, option: str) -> str:
    config = ConfigParser()
    config.read(os.path.expanduser("~/.pypirc"))

    if not config.has_option(section, option):
        raise ValueError(f"Your ~/.pypirc must define a {option} option in the {section} section")
    return config.get(section, option)


def check_ownership(users, minimum_owner_count: int = 3) -> None:
    minimum_owner_count = max(len(users), minimum_owner_count)
    packages = sorted(all_packages())
    banner(f"Checking package ownership for {len(packages)} packages")
    users = {user.lower() for user in users}
    insufficient = set()
    unowned: Dict[str, Set[Package]] = dict()

    def check_ownership(i: int, package: Package) -> None:
        banner(
            f"[{i}/{len(packages)}] checking ownership for {package}: > {minimum_owner_count} "
            f"releasers including {', '.join(users)}"
        )
        if not package.exists():
            print(f"The {package.name} package is new! There are no owners yet.")
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
            for user, unowned_packages in sorted(unowned.items()):
                formatted_unowned = "\n".join(package.name for package in sorted(packages))
                print(
                    f"PyPI account {user} needs to be added as an owner for the following "
                    f"packages:\n{formatted_unowned}",
                    file=sys.stderr,
                )

        if insufficient:
            insufficient_packages = "\n".join(package.name for package in insufficient)
            print(
                f"The following packages have fewer than {minimum_owner_count} owners but should be "
                f"setup for all releasers:\n{insufficient_packages}",
                file=sys.stderr,
            )

        sys.exit(1)


def _create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    parser_list = subparsers.add_parser("list")
    parser_list.add_argument("--with-packages", action="store_true")

    subparsers.add_parser("list-owners")
    subparsers.add_parser("check-my-ownership")

    parser_build_and_print = subparsers.add_parser("build_and_print")
    parser_build_and_print.add_argument("version")
    return parser


args = _create_parser().parse_args()

if args.command == "list":
    if args.with_packages:
        print(
            "\n".join(
                f"{package.name} {package.target} {' '.join(package.bdist_wheel_flags)}"
                for package in sorted(all_packages())
            )
        )
    else:
        print("\n".join(package.name for package in sorted(all_packages())))
elif args.command == "list-owners":
    for package in sorted(all_packages()):
        if not package.exists():
            print(
                f"The {package.name} package is new!  There are no owners yet.", file=sys.stderr,
            )
            continue
        print(f"Owners of {package.name}:")
        for owner in sorted(package.owners()):
            print(f"{owner}")
elif args.command == "check-my-ownership":
    me = get_pypi_config("server-login", "username")
    check_ownership({me})
elif args.command == "build_and_print":
    build_and_print_packages(args.version)
else:
    raise argparse.ArgumentError(f"Didn't recognise arguments {args}")
