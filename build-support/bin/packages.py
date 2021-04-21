# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import venv
import xmlrpc.client
from configparser import ConfigParser
from contextlib import contextmanager
from functools import total_ordering
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Iterable, Iterator, NamedTuple, cast
from urllib.parse import quote_plus
from xml.etree import ElementTree

import requests
from common import banner, die, green, travis_section
from reversion import reversion

# -----------------------------------------------------------------------------------------------
# Pants package definitions
# -----------------------------------------------------------------------------------------------


@total_ordering
class Package:
    def __init__(
        self, name: str, target: str, validate: Callable[[str, Path, list[str]], None]
    ) -> None:
        self.name = name
        self.target = target
        self.validate = validate

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

    def find_locally(self, *, version: str, search_dir: str | Path) -> list[Path]:
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

    def owners(self) -> set[str]:
        client = xmlrpc.client.ServerProxy("https://pypi.org/pypi")
        roles = client.package_roles(self.name)
        return {row[1] for row in roles if row[0] == "Owner"}  # type: ignore[union-attr,index]


def _pip_args(extra_pip_args: list[str]) -> tuple[str, ...]:
    return (*extra_pip_args, "--quiet", "--no-cache-dir")


def validate_pants_pkg(version: str, venv_dir: Path, extra_pip_args: list[str]) -> None:
    subprocess.run(
        [
            venv_dir / "bin/pip",
            "install",
            *_pip_args(extra_pip_args),
            f"pantsbuild.pants=={version}",
        ],
        check=True,
    )

    def run_venv_pants(args: list[str]) -> str:
        # When we do (dry-run) testing, we need to run the packaged pants. It doesn't have internal
        # backend plugins so when we execute it at the repo build root, the root pants.toml will
        # ask it to load internal backend packages and their dependencies which it doesn't have,
        # and it'll fail. To solve that problem, we load the internal backend package dependencies
        # into the pantsbuild.pants venv.
        return (
            subprocess.run(
                [
                    venv_dir / "bin/pants",
                    "--no-verify-config",
                    "--no-remote-cache-read",
                    "--no-remote-cache-write",
                    "--no-pantsd",
                    "--pythonpath=['pants-plugins']",
                    (
                        "--backend-packages=["
                        "'pants.backend.awslambda.python', "
                        "'pants.backend.python', "
                        "'pants.backend.shell', "
                        "'internal_plugins.releases'"
                        "]"
                    ),
                    *args,
                ],
                check=True,
                stdout=subprocess.PIPE,
            )
            .stdout.decode()
            .strip()
        )

    run_venv_pants(["list", "src::"])
    outputted_version = run_venv_pants(["--version"])
    if outputted_version != version:
        die(
            f"Installed version of Pants ({outputted_version}) not match requested "
            f"version ({version})!"
        )


def validate_testutil_pkg(version: str, venv_dir: Path, extra_pip_args: list[str]) -> None:
    subprocess.run(
        [
            venv_dir / "bin/pip",
            "install",
            *_pip_args(extra_pip_args),
            f"pantsbuild.pants.testutil=={version}",
        ],
        check=True,
    )
    subprocess.run(
        [
            venv_dir / "bin/python",
            "-c",
            (
                "import pants.testutil.option_util, pants.testutil.rule_runner, "
                "pants.testutil.pants_integration_test"
            ),
        ],
        check=True,
    )


PACKAGES = sorted(
    {
        # NB: This a native wheel. We expect a distinct wheel for each Python version and each
        # platform (macOS x linux).
        Package("pantsbuild.pants", "src/python/pants:pants-packaged", validate_pants_pkg),
        Package(
            "pantsbuild.pants.testutil",
            "src/python/pants/testutil:testutil_wheel",
            validate_testutil_pkg,
        ),
    }
)


# -----------------------------------------------------------------------------------------------
# Script utils
# -----------------------------------------------------------------------------------------------


class _Constants:
    def __init__(self) -> None:
        self._head_sha = (
            subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"], stdout=subprocess.PIPE, check=True
            )
            .stdout.decode()
            .strip()
        )
        self.pants_version_file = Path("src/python/pants/VERSION")
        self.pants_stable_version = self.pants_version_file.read_text().strip()

    @property
    def binary_base_url(self) -> str:
        return "https://binaries.pantsbuild.org"

    @property
    def deploy_3rdparty_wheels_path(self) -> str:
        return f"wheels/3rdparty/{self._head_sha}"

    @property
    def deploy_pants_wheels_path(self) -> str:
        return f"wheels/pantsbuild.pants/{self._head_sha}"

    @property
    def deploy_dir(self) -> Path:
        return Path.cwd() / "dist" / "deploy"

    @property
    def deploy_3rdparty_wheel_dir(self) -> Path:
        return self.deploy_dir / self.deploy_3rdparty_wheels_path

    @property
    def deploy_pants_wheel_dir(self) -> Path:
        return self.deploy_dir / self.deploy_pants_wheels_path

    @property
    def pants_unstable_version(self) -> str:
        return f"{self.pants_stable_version}+git{self._head_sha[:8]}"

    @property
    def twine_venv_dir(self) -> Path:
        return Path.cwd() / "build-support" / "twine-deps.venv"

    @property
    def python_version(self) -> str:
        return ".".join(map(str, sys.version_info[:2]))


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


@contextmanager
def set_pants_version(version: str) -> Iterator[None]:
    """Temporarily rewrite the VERSION file."""
    original_content = CONSTANTS.pants_version_file.read_text()
    CONSTANTS.pants_version_file.write_text(version)
    try:
        yield
    finally:
        CONSTANTS.pants_version_file.write_text(original_content)


def is_cross_platform(wheel_paths: Iterable[Path]) -> bool:
    return not all(wheel.name.endswith("-none-any.whl") for wheel in wheel_paths)


@contextmanager
def create_tmp_venv() -> Iterator[Path]:
    """Create a venv and return the path to it.

    Note that the venv is not sourced. You should run Path(tempdir, "bin/pip") and Path(tempdir,
    "bin/python") directly.
    """
    with TemporaryDirectory() as tempdir:
        venv.create(tempdir, with_pip=True, clear=True, symlinks=True)
        subprocess.run([Path(tempdir, "bin/pip"), "install", "--quiet", "wheel"], check=True)
        yield Path(tempdir)


def create_twine_venv() -> None:
    """Create a venv at CONSTANTS.twine_venv_dir and install Twine."""
    if CONSTANTS.twine_venv_dir.exists():
        shutil.rmtree(CONSTANTS.twine_venv_dir)
    venv.create(CONSTANTS.twine_venv_dir, with_pip=True, clear=True, symlinks=True)
    subprocess.run([CONSTANTS.twine_venv_dir / "bin/pip", "install", "--quiet", "twine"])


# -----------------------------------------------------------------------------------------------
# Build artifacts
# -----------------------------------------------------------------------------------------------


def build_pants_wheels() -> None:
    banner(f"Building Pants wheels with Python {CONSTANTS.python_version}")
    version = CONSTANTS.pants_unstable_version

    dest = CONSTANTS.deploy_pants_wheel_dir / version
    dest.mkdir(parents=True, exist_ok=True)

    args = (
        "./pants",
        # TODO(#9924).
        "--no-dynamic-ui",
        # TODO(#7654): It's not safe to use Pantsd because we're already using Pants to run
        #  this script.
        "--concurrent",
        "package",
        *(package.target for package in PACKAGES),
    )

    with set_pants_version(CONSTANTS.pants_unstable_version):
        try:
            subprocess.run(args, check=True)
        except subprocess.CalledProcessError as e:
            failed_packages = ",".join(package.name for package in PACKAGES)
            failed_targets = " ".join(package.target for package in PACKAGES)
            die(
                f"Failed to build packages {failed_packages} for {version} with targets "
                f"{failed_targets}.\n\n{e!r}",
            )

        # TODO(#10718): Allow for sdist releases. We can build an sdist for
        #  `pantsbuild.pants.testutil`, but need to wire it up to the rest of our release process.
        for package in PACKAGES:
            found_wheels = sorted(Path("dist").glob(f"{package}-{version}-*.whl"))
            # NB: For any platform-specific wheels, like pantsbuild.pants, we assume that the
            # top-level `dist` will only have wheels built for the current platform. This
            # should be safe because it is not possible to build native wheels for another
            # platform.
            if not is_cross_platform(found_wheels) and len(found_wheels) > 1:
                raise ValueError(
                    f"Found multiple wheels for {package} in the `dist/` folder, but was "
                    f"expecting only one wheel: {sorted(wheel.name for wheel in found_wheels)}."
                )
            for wheel in found_wheels:
                if not (dest / wheel.name).exists():
                    # We use `copy2` to preserve metadata.
                    shutil.copy2(wheel, dest)

    green(f"Wrote Pants wheels to {dest}.")

    banner(f"Validating Pants wheels for {CONSTANTS.python_version}.")
    create_twine_venv()
    subprocess.run([CONSTANTS.twine_venv_dir / "bin/twine", "check", dest / "*.whl"], check=True)
    green(f"Validated Pants wheels for {CONSTANTS.python_version}.")


def build_3rdparty_wheels() -> None:
    banner(f"Building 3rdparty wheels with Python {CONSTANTS.python_version}")
    dest = CONSTANTS.deploy_3rdparty_wheel_dir / CONSTANTS.pants_unstable_version
    pkg_tgts = [pkg.target for pkg in PACKAGES]
    with create_tmp_venv() as venv_tmpdir:
        deps = (
            subprocess.run(
                [
                    "./pants",
                    "--concurrent",
                    "--no-dynamic-ui",
                    "dependencies",
                    "--transitive",
                    "--type=3rdparty",
                    *pkg_tgts,
                ],
                stdout=subprocess.PIPE,
                check=True,
            )
            .stdout.decode()
            .strip()
            .splitlines()
        )
        if not deps:
            raise AssertionError(
                f"No 3rd-party dependencies detected for {pkg_tgts}. Is `./pants dependencies` "
                "broken?"
            )
        subprocess.run(
            [Path(venv_tmpdir, "bin/pip"), "wheel", f"--wheel-dir={dest}", *deps],
            check=True,
        )


def build_fs_util() -> None:
    # See https://www.pantsbuild.org/docs/contributions-rust for a description of fs_util. We
    # include it in our releases because it can be a useful standalone tool.
    with travis_section("fs_util", "Building fs_util"):
        command = ["./cargo", "build", "-p", "fs_util"]
        release_mode = os.environ.get("MODE", "") != "debug"
        if release_mode:
            command.append("--release")
        subprocess.run(command, check=True, env={**os.environ, "RUST_BACKTRACE": "1"})
        current_os = (
            subprocess.run(["build-support/bin/get_os.sh"], stdout=subprocess.PIPE, check=True)
            .stdout.decode()
            .strip()
        )
        dest_dir = (
            Path(CONSTANTS.deploy_dir)
            / "bin"
            / "fs_util"
            / current_os
            / CONSTANTS.pants_unstable_version
        )
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(
            f"src/rust/engine/target/{'release' if release_mode else 'debug'}/fs_util",
            dest_dir,
        )
        green(f"Built fs_util at {dest_dir / 'fs_util'}.")


# -----------------------------------------------------------------------------------------------
# Publish
# -----------------------------------------------------------------------------------------------


def publish() -> None:
    banner("Releasing packages to PyPI and GitHub")
    # Check prereqs.
    check_clean_git_branch()
    check_pgp()
    check_ownership({get_pypi_config("server-login", "username")})
    # Fetch and validate prebuild wheels.
    if CONSTANTS.deploy_pants_wheel_dir.exists():
        shutil.rmtree(CONSTANTS.deploy_pants_wheel_dir)
    fetch_prebuilt_wheels(CONSTANTS.deploy_dir)
    check_prebuilt_wheels_present(CONSTANTS.deploy_dir)
    reversion_prebuilt_wheels()
    # Release.
    create_twine_venv()
    subprocess.run(
        [
            CONSTANTS.twine_venv_dir / "bin/twine",
            "--sign",
            f"--sign-with={get_pgp_program_name()}",
            f"--identity={get_pgp_key_id()}",
        ],
        check=True,
    )
    tag_release()
    banner("Successfully released packages to PyPI and GitHub")


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
    valid_branch_pattern = r"^(main)|([0-9]+\.[0-9]+\.x)$"
    git_branch = get_git_branch()
    if not re.match(valid_branch_pattern, git_branch):
        die(
            "On an invalid branch. You must either be on `main` or a release branch like "
            f"`2.4.x`. Detected: {git_branch}"
        )


def check_pgp() -> None:
    banner("Checking PGP setup")
    key = get_pgp_key_id()
    if not key:
        die("You must set up a PGP key. See https://www.pantsbuild.org/docs/release-process.")
    print("Found the following key for release signing:\n")
    subprocess.run([get_pgp_program_name(), "-k", key])
    key_confirmation = input("\nIs this the correct key? [Y/n]: ")
    if key_confirmation and key_confirmation.lower() != "y":
        die(
            "Please configure the key you intend to use. See "
            "https://www.pantsbuild.org/docs/release-process."
        )


def check_ownership(users, minimum_owner_count: int = 3) -> None:
    minimum_owner_count = max(len(users), minimum_owner_count)
    banner(f"Checking package ownership for {len(PACKAGES)} packages")
    users = {user.lower() for user in users}
    insufficient = set()
    unowned: dict[str, set[Package]] = dict()

    def check(i: int, pkg: Package) -> None:
        banner(
            f"[{i}/{len(PACKAGES)}] checking ownership for {pkg}: > {minimum_owner_count} "
            f"releasers including {', '.join(users)}"
        )
        if not pkg.exists_on_pypi():
            print(f"The {pkg.name} package is new! There are no owners yet.")
            return

        owners = pkg.owners()
        if len(owners) <= minimum_owner_count:
            insufficient.add(pkg)

        difference = users.difference(owners)
        for d in difference:
            unowned.setdefault(d, set()).add(pkg)

    for i, package in enumerate(PACKAGES):
        check(i, package)

    if unowned:
        for user, unowned_packages in sorted(unowned.items()):
            formatted_unowned = "\n".join(package.name for package in PACKAGES)
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


def reversion_prebuilt_wheels() -> None:
    # First, rewrite to manylinux. See https://www.python.org/dev/peps/pep-0599/. We build on
    # Centos7, so use manylinux2014.
    source_platform = "linux_x86_64"
    dest_platform = "manylinux2014_x86_64"
    unstable_wheel_dir = CONSTANTS.deploy_pants_wheel_dir / CONSTANTS.pants_unstable_version
    for whl in unstable_wheel_dir.glob(f"*{source_platform}.whl"):
        whl.rename(str(whl).replace(source_platform, dest_platform))

    # Now, reversion to use the STABLE_VERSION.
    stable_wheel_dir = CONSTANTS.deploy_pants_wheel_dir / CONSTANTS.pants_stable_version
    stable_wheel_dir.mkdir(parents=True, exist_ok=True)
    for whl in unstable_wheel_dir.glob("*.whl"):
        reversion(
            whl_file=str(whl),
            dest_dir=str(stable_wheel_dir),
            target_version=CONSTANTS.pants_stable_version,
            extra_globs=["pants/VERSION"],
        )


def tag_release() -> None:
    tag_name = f"release_{CONSTANTS.pants_stable_version}"
    subprocess.run(
        [
            "git",
            "tag",
            "-f",
            f"--local-user={get_pgp_key_id()}",
            "-m",
            f"pantsbuild.pants release {CONSTANTS.pants_stable_version}",
            tag_name,
        ],
        check=True,
    )
    subprocess.run(
        ["git", "push", "-f", "git@github.com:pantsbuild/pants.git", tag_name], check=True
    )


# -----------------------------------------------------------------------------------------------
# Test release & dry run
# -----------------------------------------------------------------------------------------------


def dry_run_install() -> None:
    banner("Performing a dry run release")
    build_pants_wheels()
    build_3rdparty_wheels()
    install_and_test_packages(
        CONSTANTS.pants_unstable_version,
        extra_pip_args=[
            "--only-binary=:all:",
            "-f",
            str(CONSTANTS.deploy_3rdparty_wheel_dir / CONSTANTS.pants_unstable_version),
            "-f",
            str(CONSTANTS.deploy_pants_wheel_dir / CONSTANTS.pants_unstable_version),
        ],
    )
    banner("Dry run release succeeded")


def test_release() -> None:
    banner("Installing and testing the latest released packages")
    install_and_test_packages(CONSTANTS.pants_stable_version)
    banner("Successfully installed and tested the latest released packages")


def install_and_test_packages(version: str, *, extra_pip_args: list[str] | None = None) -> None:
    with create_tmp_venv() as venv_tmpdir:
        for pkg in PACKAGES:
            pip_req = f"{pkg.name}=={version}"
            banner(f"Installing and testing {pip_req}")
            pkg.validate(version, venv_tmpdir, extra_pip_args or [])
            green(f"Tests succeeded for {pip_req}")


# -----------------------------------------------------------------------------------------------
# Release introspection
# -----------------------------------------------------------------------------------------------


def list_owners() -> None:
    for package in PACKAGES:
        if not package.exists_on_pypi():
            print(f"The {package.name} package is new!  There are no owners yet.", file=sys.stderr)
            continue
        formatted_owners = "\n".join(sorted(package.owners()))
        print(f"Owners of {package.name}:\n{formatted_owners}\n")


def list_packages() -> None:
    print("\n".join(package.name for package in PACKAGES))


class PrebuiltWheel(NamedTuple):
    path: str
    url: str

    @classmethod
    def create(cls, path: str) -> PrebuiltWheel:
        return cls(path, quote_plus(path))


def determine_prebuilt_wheels() -> list[PrebuiltWheel]:
    def determine_wheels(wheel_path: str) -> list[PrebuiltWheel]:
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
        *determine_wheels(CONSTANTS.deploy_pants_wheels_path),
        *determine_wheels(CONSTANTS.deploy_3rdparty_wheels_path),
    ]


def list_prebuilt_wheels() -> None:
    print(
        "\n".join(
            f"{CONSTANTS.binary_base_url}/{wheel.url}" for wheel in determine_prebuilt_wheels()
        )
    )


# -----------------------------------------------------------------------------------------------
# Fetch and check prebuilt wheels
# -----------------------------------------------------------------------------------------------


# TODO: possibly parallelize through httpx and asyncio.
def fetch_prebuilt_wheels(destination_dir: str | Path) -> None:
    banner(f"Fetching pre-built wheels for {CONSTANTS.pants_unstable_version}")
    print(f"Saving to {destination_dir}.\n", file=sys.stderr)
    session = requests.Session()
    session.mount(CONSTANTS.binary_base_url, requests.adapters.HTTPAdapter(max_retries=4))
    for wheel in determine_prebuilt_wheels():
        full_url = f"{CONSTANTS.binary_base_url}/{wheel.url}"
        print(f"Fetching {full_url}", file=sys.stderr)
        response = session.get(full_url)
        response.raise_for_status()
        print(file=sys.stderr)

        dest = Path(destination_dir, wheel.path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(response.content)


def check_prebuilt_wheels_present(check_dir: str | Path) -> None:
    banner(f"Checking prebuilt wheels for {CONSTANTS.pants_unstable_version}")
    missing_packages = []
    for package in PACKAGES:
        local_files = package.find_locally(
            version=CONSTANTS.pants_unstable_version, search_dir=check_dir
        )
        if not local_files:
            missing_packages.append(package.name)
            continue
        if is_cross_platform(local_files) and len(local_files) != 6:
            formatted_local_files = ", ".join(f.name for f in local_files)
            missing_packages.append(
                f"{package.name} (expected 6 wheels, {{macosx, linux}} x {{cp37m, cp38, cp39}}, "
                f"but found {formatted_local_files})"
            )
    if missing_packages:
        formatted_missing = "\n  ".join(missing_packages)
        die(f"Failed to find prebuilt wheels:\n  {formatted_missing}")
    green(f"All {len(PACKAGES)} pantsbuild.pants packages were fetched and are valid.")


# -----------------------------------------------------------------------------------------------
# main()
# -----------------------------------------------------------------------------------------------


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("publish")
    subparsers.add_parser("dry-run-install")
    subparsers.add_parser("test-release")
    subparsers.add_parser("build-pants-wheels")
    subparsers.add_parser("build-3rdparty-wheels")
    subparsers.add_parser("build-fs-util")
    subparsers.add_parser("list-owners")
    subparsers.add_parser("list-packages")
    subparsers.add_parser("list-prebuilt-wheels")

    parser_fetch_prebuilt_wheels = subparsers.add_parser("fetch-and-check-prebuilt-wheels")
    parser_fetch_prebuilt_wheels.add_argument("--wheels-dest")

    return parser


def main() -> None:
    args = create_parser().parse_args()
    if args.command == "publish":
        publish()
    if args.command == "dry-run-install":
        dry_run_install()
    if args.command == "test-release":
        test_release()
    if args.command == "build-pants-wheels":
        build_pants_wheels()
    if args.command == "build-3rdparty-wheels":
        build_3rdparty_wheels()
    if args.command == "build-fs-util":
        build_fs_util()
    if args.command == "list-owners":
        list_owners()
    if args.command == "list-packages":
        list_packages()
    if args.command == "list-prebuilt-wheels":
        list_prebuilt_wheels()
    if args.command == "fetch-and-check-prebuilt-wheels":
        with TemporaryDirectory() as tempdir:
            dest = args.wheels_dest or tempdir
            fetch_prebuilt_wheels(dest)
            check_prebuilt_wheels_present(dest)


if __name__ == "__main__":
    main()
