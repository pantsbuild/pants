# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import os
import re
import subprocess
import sys
from collections import defaultdict
from configparser import ConfigParser
from functools import total_ordering
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, List, NamedTuple, Optional, Set, Tuple, cast
from urllib.parse import quote_plus
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup
from common import banner, die, green

# -----------------------------------------------------------------------------------------------
# Pants package definitions
# -----------------------------------------------------------------------------------------------


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

    def find_locally(self, *, version: str, search_dir: str) -> List[Path]:
        return list(Path(search_dir).rglob(f"{self.name}-{version}-*.whl"))

    def exists_on_pypi(self) -> bool:  # type: ignore[return]
        response = requests.head(f"https://pypi.org/project/{self.name}/")
        if response.ok:
            return True
        if response.status_code == 404:
            return False
        response.raise_for_status()

    def latest_published_version(self) -> str:
        json_data = requests.get(f"https://pypi.org/pypi/{self.name}/json").json()
        return cast(str, json_data["info"]["version"])

    def owners(self) -> Set[str]:
        url_content = requests.get(
            f"https://pypi.org/project/{self.name}/{self.latest_published_version()}/"
        ).text
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
    return {
        Package(
            "pantsbuild.pants",
            "//src/python/pants:pants-packaged",
            bdist_wheel_flags=("--py-limited-api", "cp36"),
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


# -----------------------------------------------------------------------------------------------
# Script utils
# -----------------------------------------------------------------------------------------------


class _Constants:
    def __init__(self) -> None:
        # self._head_sha = (
        #     subprocess.run(
        #         ["git", "rev-parse", "--verify", "HEAD"], stdout=subprocess.PIPE, check=True
        #     )
        #     .stdout.decode()
        #     .strip()
        # )
        self._head_sha = "f2521cab6fb8bed3b8b12b479369280b2dee2c9f"
        self.pants_stable_version = Path("src/python/pants/VERSION").read_text().strip()

    @property
    def binary_base_url(self) -> str:
        return "https://binaries.pantsbuild.org"

    @property
    def deploy_3rdparty_wheels_path(self) -> str:
        return f"wheels/3rdparty/{self._head_sha}"

    @property
    def deploy_pants_wheel_path(self) -> str:
        return f"wheels/pantsbuild.pants/{self._head_sha}"

    @property
    def pants_unstable_version(self) -> str:
        return f"{self.pants_stable_version}+git{self._head_sha[:8]}"


CONSTANTS = _Constants()


def get_pypi_config(section: str, option: str) -> str:
    config = ConfigParser()
    config.read(os.path.expanduser("~/.pypirc"))
    if not config.has_option(section, option):
        raise ValueError(f"Your ~/.pypirc must define a {option} option in the {section} section")
    return config.get(section, option)


def get_git_branch() -> str:
    return (
        subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], stdout=subprocess.PIPE, check=True
        )
        .stdout.decode()
        .strip()
    )


def get_pgp_key_id() -> str:
    return (
        subprocess.run(["git", "config", "--get", "user.signingkey"], stdout=subprocess.PIPE)
        .stdout.decode()
        .strip()
    )


def get_pgp_program_name() -> str:
    configured_name = (
        subprocess.run(["git", "config", "--get", "gpg.program"], stdout=subprocess.PIPE)
        .stdout.decode()
        .strip()
    )
    return configured_name or "gpg"


# -----------------------------------------------------------------------------------------------
# Script commands
# -----------------------------------------------------------------------------------------------


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


def check_clean_git_branch() -> None:
    banner("Checking for a clean Git branch")
    git_status = (
        subprocess.run(["git", "status", "--porcelain"], stdout=subprocess.PIPE, check=True)
        .stdout.decode()
        .strip()
    )
    if git_status:
        die(
            "Uncommitted changes detected when running `git status`. You must be on a clean branch "
            "to release."
        )
    valid_branch_pattern = r"^(master)|([0-9]+\.[0-9]+\.x)$"
    git_branch = get_git_branch()
    if not re.match(valid_branch_pattern, git_branch):
        die(
            "On an invalid branch. You must either be on `master` or a release branch like "
            f"`1.27.x`. Detected: {git_branch}"
        )


def check_pgp() -> None:
    banner("Checking PGP setup")
    key = get_pgp_key_id()
    if not key:
        die("You must set up a PGP key. See https://pants.readme.io/docs/release-process.")
    print("Found the following key for release signing:\n")
    subprocess.run([get_pgp_program_name(), "-k", key])
    key_confirmation = input("\nIs this the correct key? [Y/n]: ")
    if key_confirmation and key_confirmation.lower() != "y":
        die(
            "Please configure the key you intend to use. See "
            "https://pants.readme.io/docs/release-process."
        )


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
        if not package.exists_on_pypi():
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

    if unowned:
        for user, unowned_packages in sorted(unowned.items()):
            formatted_unowned = "\n".join(package.name for package in sorted(packages))
            print(
                f"PyPI account {user} needs to be added as an owner for the following "
                f"packages:\n{formatted_unowned}",
                file=sys.stderr,
            )
        raise SystemExit()

    if insufficient:
        insufficient_packages = "\n".join(package.name for package in insufficient)
        die(
            f"The following packages have fewer than {minimum_owner_count} owners but should be "
            f"setup for all releasers:\n{insufficient_packages}",
        )


def check_release_prereqs() -> None:
    check_clean_git_branch()
    check_pgp()
    me = get_pypi_config("server-login", "username")
    check_ownership({me})


def list_owners() -> None:
    for package in sorted(all_packages()):
        if not package.exists_on_pypi():
            print(
                f"The {package.name} package is new!  There are no owners yet.", file=sys.stderr,
            )
            continue
        formatted_owners = "\n".join(sorted(package.owners()))
        print(f"Owners of {package.name}:\n{formatted_owners}\n")


def list_packages() -> None:
    print("\n".join(package.name for package in sorted(all_packages())))


class PrebuiltWheel(NamedTuple):
    path: str
    url: str

    @classmethod
    def create(cls, path: str) -> "PrebuiltWheel":
        return cls(path, quote_plus(path))

    def format(self) -> str:
        return f"{self.path}\t{self.url}"


def determine_prebuilt_wheels() -> List[PrebuiltWheel]:
    """List wheels as tab-separated tuples of filename and URL-encoded name."""

    def determine_wheels(wheel_path: str) -> List[PrebuiltWheel]:
        response = requests.get(f"{CONSTANTS.binary_base_url}/?prefix={wheel_path}")
        xml_root = ElementTree.fromstring(response.text)
        return [
            PrebuiltWheel.create(key.text)  # type: ignore[arg-type]
            for key in xml_root.findall(
                path="s3:Contents/s3:Key",
                namespaces={"s3": "http://s3.amazonaws.com/doc/2006-03-01/"},
            )
        ]

    return [
        *determine_wheels(CONSTANTS.deploy_pants_wheel_path),
        *determine_wheels(CONSTANTS.deploy_3rdparty_wheels_path),
    ]


def list_prebuilt_wheels() -> None:
    print("\n".join(wheel.format() for wheel in determine_prebuilt_wheels()))


# TODO: possibly parallelize through httpx and asyncio.
def fetch_prebuilt_wheels(destination_dir: str) -> None:
    banner(f"Fetching pre-built wheels for {CONSTANTS.pants_unstable_version}")
    print(f"Saving to {destination_dir}.\n", file=sys.stderr)
    for wheel in determine_prebuilt_wheels():
        full_url = f"{CONSTANTS.binary_base_url}/{wheel.url}"
        print(f"Fetching {full_url}", file=sys.stderr)
        response = requests.get(full_url)
        response.raise_for_status()
        print(file=sys.stderr)

        dest = Path(destination_dir, wheel.path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(response.content)


def check_prebuilt_wheels(check_dir: str) -> None:
    banner(f"Checking prebuilt wheels for {CONSTANTS.pants_unstable_version}")
    missing_packages = []
    for package in sorted(all_packages()):
        local_files = package.find_locally(
            version=CONSTANTS.pants_unstable_version, search_dir=check_dir
        )
        if not local_files:
            missing_packages.append(package.name)
            continue

        # If the package is cross platform, confirm that we have whls for two platforms.
        is_cross_platform = not all(
            local_file.name.endswith("-none-any.whl") for local_file in local_files
        )
        if is_cross_platform and len(local_files) != 2:
            formatted_local_files = ", ".join(f.name for f in local_files)
            missing_packages.append(
                f"{package.name} (expected a macOS wheel and a linux wheel, but found "
                f"{formatted_local_files})"
            )

    if missing_packages:
        formatted_missing = "\n  ".join(missing_packages)
        die(f"Failed to find prebuilt wheels:\n  {formatted_missing}")
    green(f"All {len(all_packages())} pantsbuild.pants packages were fetched and are valid.")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("check-release-prereqs")
    subparsers.add_parser("list-owners")
    subparsers.add_parser("list-packages")
    subparsers.add_parser("list-prebuilt-wheels")

    parser_fetch_prebuilt_wheels = subparsers.add_parser("fetch-and-check-prebuilt-wheels")
    parser_fetch_prebuilt_wheels.add_argument("--wheels-dest")

    parser_build_and_print = subparsers.add_parser("build-and-print")
    parser_build_and_print.add_argument("version")
    return parser


def main() -> None:
    args = create_parser().parse_args()
    if args.command == "check-release-prereqs":
        check_release_prereqs()
    if args.command == "list-owners":
        list_owners()
    if args.command == "list-packages":
        list_packages()
    if args.command == "list-prebuilt-wheels":
        list_prebuilt_wheels()
    if args.command == "build-and-print":
        build_and_print_packages(args.version)
    if args.command == "fetch-and-check-prebuilt-wheels":
        with TemporaryDirectory() as tempdir:
            dest = args.wheels_dest or tempdir
            fetch_prebuilt_wheels(dest)
            check_prebuilt_wheels(dest)


if __name__ == "__main__":
    main()
