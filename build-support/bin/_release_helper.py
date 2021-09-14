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
from time import sleep
from typing import Callable, Iterable, Iterator, NamedTuple, cast
from urllib.parse import quote_plus
from xml.etree import ElementTree

import requests
from common import banner, die, green
from reversion import reversion

from pants.util.strutil import strip_prefix

# -----------------------------------------------------------------------------------------------
# Pants package definitions
# -----------------------------------------------------------------------------------------------

_known_packages = [
    # The packages we currently publish.
    "pantsbuild.pants",
    "pantsbuild.pants.testutil",
    # Legacy/deprecated packages that we no longer publish, but still want to verify settings for.
    "pantsbuild.pants.contrib.android",
    "pantsbuild.pants.contrib.avro",
    "pantsbuild.pants.contrib.awslambda-python",
    "pantsbuild.pants.contrib.buildgen",
    "pantsbuild.pants.contrib.codeanalysis",
    "pantsbuild.pants.contrib.confluence",
    "pantsbuild.pants.contrib.cpp",
    "pantsbuild.pants.contrib.errorprone",
    "pantsbuild.pants.contrib.findbugs",
    "pantsbuild.pants.contrib.go",
    "pantsbuild.pants.contrib.googlejavaformat",
    "pantsbuild.pants.contrib.haskell",
    "pantsbuild.pants.contrib.jax-ws",
    "pantsbuild.pants.contrib.mypy",
    "pantsbuild.pants.contrib.node",
    "pantsbuild.pants.contrib.python.checks",
    "pantsbuild.pants.contrib.python.checks.checker",
    "pantsbuild.pants.contrib.scalajs",
    "pantsbuild.pants.contrib.scrooge",
    "pantsbuild.pants.contrib.spindle",
    "pantsbuild.pants.contrib.thrifty",
    "pantsbuild.pants.testinfra",
]

_expected_owners = {"benjyw", "John.Sirois", "stuhood"}

_expected_maintainers = {"EricArellano", "gshuflin", "illicitonion", "wisechengyi"}


class PackageAccessValidator:
    @classmethod
    def validate_all(cls):
        instance = cls()
        for pkg_name in _known_packages:
            instance.validate_package_access(pkg_name)

    def __init__(self):
        self._client = xmlrpc.client.ServerProxy("https://pypi.org/pypi")

    @property
    def client(self):
        # The PyPI XML-RPC API requires at least 1 second between requests, or it rejects them
        # with HTTPTooManyRequests.
        sleep(1.0)
        return self._client

    @staticmethod
    def validate_role_sets(role: str, actual: set[str], expected: set[str]) -> str:
        err_msg = ""
        if actual != expected:
            expected_not_actual = sorted(expected - actual)
            actual_not_expected = sorted(actual - expected)
            if expected_not_actual:
                err_msg += f"Missing expected {role}s: {','.join(expected_not_actual)}."
            if actual_not_expected:
                err_msg += f"Found unexpected {role}s: {','.join(actual_not_expected)}"
        return err_msg

    def validate_package_access(self, pkg_name: str) -> None:
        actual_owners = set()
        actual_maintainers = set()
        for role_assignment in self.client.package_roles(pkg_name):
            role, username = role_assignment
            if role == "Owner":
                actual_owners.add(username)
            elif role == "Maintainer":
                actual_maintainers.add(username)
            else:
                raise ValueError(f"Unrecognized role {role} for user {username}")

        err_msg = ""
        err_msg += self.validate_role_sets("owner", actual_owners, _expected_owners)
        err_msg += self.validate_role_sets("maintainer", actual_maintainers, _expected_maintainers)

        if err_msg:
            die(f"Role discrepancies for {pkg_name}: {err_msg}")

        print(f"Roles for package {pkg_name} as expected.")


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
        def can_publish(role: str) -> bool:
            return role in {"Owner", "Maintainer"}

        client = xmlrpc.client.ServerProxy("https://pypi.org/pypi")
        roles = client.package_roles(self.name)
        return {row[1] for row in roles if can_publish(row[0])}  # type: ignore[union-attr,index]


def _pip_args(extra_pip_args: list[str]) -> tuple[str, ...]:
    return (*extra_pip_args, "--quiet", "--no-cache-dir")


def validate_pants_pkg(version: str, venv_dir: Path, extra_pip_args: list[str]) -> None:
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

    subprocess.run(
        [
            venv_dir / "bin/pip",
            "install",
            *_pip_args(extra_pip_args),
            f"pantsbuild.pants=={version}",
        ],
        check=True,
    )
    outputted_version = run_venv_pants(["--version"])
    if outputted_version != version:
        die(
            f"Installed version of Pants ({outputted_version}) did not match requested "
            f"version ({version})!"
        )
    run_venv_pants(["list", "src::"])


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


# NB: This a native wheel. We expect a distinct wheel for each Python version and each
# platform (macOS_x86 x macos_arm x linux).
PANTS_PKG = Package("pantsbuild.pants", "src/python/pants:pants-packaged", validate_pants_pkg)
TESTUTIL_PKG = Package(
    "pantsbuild.pants.testutil",
    "src/python/pants/testutil:testutil_wheel",
    validate_testutil_pkg,
)
PACKAGES = sorted({PANTS_PKG, TESTUTIL_PKG})


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
        die(f"Your ~/.pypirc must define a {option} option in the {section} section")
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
        subprocess.run(
            ["git", "config", "--get", "user.signingkey"], stdout=subprocess.PIPE, check=False
        )
        .stdout.decode()
        .strip()
    )


def get_pgp_program_name() -> str:
    configured_name = (
        subprocess.run(
            ["git", "config", "--get", "gpg.program"], stdout=subprocess.PIPE, check=False
        )
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
    subprocess.run(
        [CONSTANTS.twine_venv_dir / "bin/pip", "install", "--quiet", "twine"], check=True
    )


@contextmanager
def download_pex_bin() -> Iterator[Path]:
    """Download PEX and return the path to the binary."""
    try:
        pex_version = next(
            strip_prefix(ln, "pex==").rstrip()
            for ln in Path("3rdparty/python/requirements.txt").read_text().splitlines()
            if ln.startswith("pex==")
        )
    except (FileNotFoundError, StopIteration) as exc:
        die(
            "Could not find a requirement starting with `pex==` in "
            f"3rdparty/python/requirements.txt: {repr(exc)}"
        )

    with TemporaryDirectory() as tempdir:
        resp = requests.get(
            f"https://github.com/pantsbuild/pex/releases/download/v{pex_version}/pex"
        )
        resp.raise_for_status()
        result = Path(tempdir, "pex")
        result.write_bytes(resp.content)
        yield result


# -----------------------------------------------------------------------------------------------
# Build artifacts
# -----------------------------------------------------------------------------------------------


def build_all_wheels() -> None:
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
                die(
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
            die(
                f"No 3rd-party dependencies detected for {pkg_tgts}. Is `./pants dependencies` "
                "broken?"
            )
        subprocess.run(
            [str(Path(venv_tmpdir, "bin/pip")), "wheel", f"--wheel-dir={dest}", *deps],
            check=True,
        )
        green(f"Wrote 3rdparty wheels to {dest}")


def build_fs_util() -> None:
    # See https://www.pantsbuild.org/docs/contributions-rust for a description of fs_util. We
    # include it in our releases because it can be a useful standalone tool.
    banner("Building fs_util")
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


# TODO: We should be using `./pants package` and `pex_binary` for this...If Pants is lacking in
#  capabilities, we should improve Pants. When porting, using `runtime_package_dependencies` to do
#  the validation.
def build_pex(fetch: bool) -> None:
    if fetch:
        extra_pex_args = [
            f"--platform={plat}-{abi}"
            for plat in ("linux_x86_64", "linux_aarch64", "macosx_10.15_x86_64")
            for abi in ("cp-37-m", "cp-38-cp38", "cp-39-cp39")
        ]
        pex_name = f"pants.{CONSTANTS.pants_unstable_version}.pex"
        banner(f"Building {pex_name} by fetching wheels.")
    else:
        extra_pex_args = [f"--python={sys.executable}"]
        plat = os.uname()[0].lower()
        py = f"cp{''.join(map(str, sys.version_info[:2]))}"
        pex_name = f"pants.{CONSTANTS.pants_unstable_version}.{plat}-{py}.pex"
        banner(f"Building {pex_name} by building wheels.")

    if CONSTANTS.deploy_dir.exists():
        shutil.rmtree(CONSTANTS.deploy_dir)
    CONSTANTS.deploy_dir.mkdir(parents=True)

    if fetch:
        fetch_prebuilt_wheels(CONSTANTS.deploy_dir, include_3rdparty=True)
        check_pants_wheels_present(CONSTANTS.deploy_dir)
    else:
        build_pants_wheels()
        build_3rdparty_wheels()

    dest = Path("dist") / pex_name
    with download_pex_bin() as pex_bin:
        subprocess.run(
            [
                sys.executable,
                str(pex_bin),
                "-o",
                str(dest),
                "--no-build",
                "--no-pypi",
                "--disable-cache",
                "-f",
                str(CONSTANTS.deploy_pants_wheel_dir / CONSTANTS.pants_unstable_version),
                "-f",
                str(CONSTANTS.deploy_3rdparty_wheel_dir / CONSTANTS.pants_unstable_version),
                "--no-strip-pex-env",
                "--console-script=pants",
                *extra_pex_args,
                f"pantsbuild.pants=={CONSTANTS.pants_unstable_version}",
            ],
            check=True,
        )

    if os.environ.get("PANTS_PEX_RELEASE", "") == "STABLE":
        stable_dest = CONSTANTS.deploy_dir / "pex" / f"pants.{CONSTANTS.pants_stable_version}.pex"
        stable_dest.parent.mkdir(parents=True, exist_ok=True)
        dest.rename(stable_dest)
        dest = stable_dest
    green(f"Built {dest}")

    subprocess.run([sys.executable, str(dest), "--version"], check=True)
    green(f"Validated {dest}")


# -----------------------------------------------------------------------------------------------
# Publish
# -----------------------------------------------------------------------------------------------


def publish() -> None:
    banner("Releasing to PyPI and GitHub")
    # Check prereqs.
    check_clean_git_branch()
    check_pgp()
    check_roles()

    # Fetch and validate prebuilt wheels.
    if CONSTANTS.deploy_pants_wheel_dir.exists():
        shutil.rmtree(CONSTANTS.deploy_pants_wheel_dir)
    fetch_prebuilt_wheels(CONSTANTS.deploy_dir, include_3rdparty=False)
    check_pants_wheels_present(CONSTANTS.deploy_dir)
    reversion_prebuilt_wheels()

    # Release.
    create_twine_venv()
    upload_wheels_via_twine()
    tag_release()
    banner("Successfully released to PyPI and GitHub")
    prompt_apple_silicon()
    prompt_to_generate_docs()


def publish_apple_silicon() -> None:
    banner("Building and publishing an Apple Silicon wheel")
    if os.environ.get("USE_PY39") != "true":
        die("Must set `USE_PY39=true` when building for Apple Silicon.")
    if os.environ.get("MODE") == "debug":
        die("Must build Rust in release mode, not debug. Please run `unset MODE`.")
    check_clean_git_branch()
    check_pgp()
    check_roles()

    dest_dir = CONSTANTS.deploy_pants_wheel_dir / CONSTANTS.pants_stable_version
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    subprocess.run(
        [
            "./pants",
            "--concurrent",
            f"--pants-distdir={dest_dir}",
            "package",
            PANTS_PKG.target,
        ],
        check=True,
    )
    expected_whl = (
        dest_dir
        / f"pantsbuild.pants-{CONSTANTS.pants_stable_version}-cp39-cp39-macosx_11_0_arm64.whl"
    )
    if not expected_whl.exists():
        die(
            f"Failed to find {expected_whl}. Are you running from the correct platform and "
            f"macOS version?"
        )

    create_twine_venv()
    subprocess.run([CONSTANTS.twine_venv_dir / "bin/twine", "check", expected_whl], check=True)
    upload_wheels_via_twine()
    banner("Successfully released Apple Silicon wheel to PyPI")


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
    subprocess.run([get_pgp_program_name(), "-k", key], check=True)
    key_confirmation = input("\nIs this the correct key? [Y/n]: ")
    if key_confirmation and key_confirmation.lower() != "y":
        die(
            "Please configure the key you intend to use. See "
            "https://www.pantsbuild.org/docs/release-process."
        )


def check_roles() -> None:
    # Check that the packages we plan to publish are correctly owned.
    banner("Checking current user.")
    username = get_pypi_config("server-login", "username")
    if (
        username != "__token__"  # See: https://pypi.org/help/#apitoken
        and username not in _expected_owners
        and username not in _expected_maintainers
    ):
        die(f"User {username} not authorized to publish.")
    banner("Checking package roles.")
    validator = PackageAccessValidator()
    for pkg in PACKAGES:
        if pkg.name not in _known_packages:
            die(f"Unknown package {pkg}")
        validator.validate_package_access(pkg.name)


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


def upload_wheels_via_twine() -> None:
    subprocess.run(
        [
            str(CONSTANTS.twine_venv_dir / "bin/twine"),
            "upload",
            "--sign",
            f"--sign-with={get_pgp_program_name()}",
            f"--identity={get_pgp_key_id()}",
            "--skip-existing",  # Makes the upload idempotent.
            str(CONSTANTS.deploy_pants_wheel_dir / CONSTANTS.pants_stable_version / "*.whl"),
        ],
        check=True,
    )


def prompt_apple_silicon() -> None:
    input(
        f"We need to release for Apple Silicon. Please message Eric on Slack asking to release "
        f"for {CONSTANTS.pants_stable_version}.\n\n"
        f"(You do not need to wait for Eric to finish his part. You can continue in the release "
        f"process once you've messaged him.)"
        f"\n\nHit enter when you've messaged Eric: "
    )


def prompt_to_generate_docs() -> None:
    has_docs_access = input(
        "\nThe docs now need to be regenerated. Do you already have editing access to "
        "readme.com? [Y/n]: "
    )
    # This URL will work regardless of the current version, so long as we don't delete 2.5 from
    # the docs.
    api_key_url = "https://dash.readme.com/project/pants/v2.5/api-key"
    docs_cmd = "./pants run build-support/bin/generate_docs.py -- --sync --api-key <key>"
    if has_docs_access and has_docs_access.lower() != "y":
        print(
            "\nPlease ask in the #maintainers Slack channel to be added to Readme.com. Please "
            "enable two-factor authentication!\n\n"
            f"Then go to {api_key_url} to find your API key. Run this command:\n\n\t{docs_cmd}\n\n"
            "(If you are not comfortable getting permissions, you can ask another maintainer to "
            "run this script in the #maintainers Slack.)"
        )
    else:
        print(
            f"\nPlease go to {api_key_url} to find your API key. Then, run this command:\n\n"
            f"\t{docs_cmd}"
        )


# -----------------------------------------------------------------------------------------------
# Test release
# -----------------------------------------------------------------------------------------------


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


class PrebuiltWheel(NamedTuple):
    path: str
    url: str

    @classmethod
    def create(cls, path: str) -> PrebuiltWheel:
        return cls(path, quote_plus(path))


def determine_prebuilt_wheels(*, include_3rdparty: bool) -> list[PrebuiltWheel]:
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

    res = determine_wheels(CONSTANTS.deploy_pants_wheels_path)
    if include_3rdparty:
        res.extend(determine_wheels(CONSTANTS.deploy_3rdparty_wheels_path))
    return res


def list_prebuilt_wheels() -> None:
    print(
        "\n".join(
            f"{CONSTANTS.binary_base_url}/{wheel.url}"
            for wheel in determine_prebuilt_wheels(include_3rdparty=True)
        )
    )


# -----------------------------------------------------------------------------------------------
# Fetch and check prebuilt wheels
# -----------------------------------------------------------------------------------------------


def fetch_prebuilt_wheels(destination_dir: str | Path, *, include_3rdparty: bool) -> None:
    banner(f"Fetching pre-built wheels for {CONSTANTS.pants_unstable_version}")
    print(f"Saving to {destination_dir}.\n", file=sys.stderr)
    session = requests.Session()
    session.mount(CONSTANTS.binary_base_url, requests.adapters.HTTPAdapter(max_retries=4))
    for wheel in determine_prebuilt_wheels(include_3rdparty=include_3rdparty):
        full_url = f"{CONSTANTS.binary_base_url}/{wheel.url}"
        print(f"Fetching {full_url}", file=sys.stderr)
        response = session.get(full_url)
        response.raise_for_status()
        print(file=sys.stderr)

        dest = Path(destination_dir, wheel.path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(response.content)


def check_pants_wheels_present(check_dir: str | Path) -> None:
    banner(f"Checking prebuilt wheels for {CONSTANTS.pants_unstable_version}")
    missing_packages = []
    for package in PACKAGES:
        local_files = package.find_locally(
            version=CONSTANTS.pants_unstable_version, search_dir=check_dir
        )
        if not local_files:
            missing_packages.append(package.name)
            continue
        if is_cross_platform(local_files) and len(local_files) != 9:
            formatted_local_files = ", ".join(f.name for f in local_files)
            missing_packages.append(
                f"{package.name} (expected 9 wheels, {{macosx, linux_x86_64, linux_arm64}} x {{cp37m, cp38, cp39}}, "
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
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("publish")
    subparsers.add_parser("publish-apple-silicon")
    subparsers.add_parser("test-release")
    subparsers.add_parser("build-wheels")
    subparsers.add_parser("build-fs-util")
    subparsers.add_parser("build-local-pex")
    subparsers.add_parser("build-universal-pex")
    subparsers.add_parser("validate-roles")
    subparsers.add_parser("list-prebuilt-wheels")
    subparsers.add_parser("check-pants-wheels")
    return parser


def main() -> None:
    args = create_parser().parse_args()
    if args.command == "publish":
        publish()
    if args.command == "publish-apple-silicon":
        publish_apple_silicon()
    if args.command == "test-release":
        test_release()
    if args.command == "build-wheels":
        build_all_wheels()
    if args.command == "build-fs-util":
        build_fs_util()
    if args.command == "build-local-pex":
        build_pex(fetch=False)
    if args.command == "build-universal-pex":
        build_pex(fetch=True)
    if args.command == "validate-roles":
        PackageAccessValidator.validate_all()
    if args.command == "list-prebuilt-wheels":
        list_prebuilt_wheels()
    if args.command == "check-pants-wheels":
        with TemporaryDirectory() as tempdir:
            fetch_prebuilt_wheels(tempdir, include_3rdparty=False)
            check_pants_wheels_present(tempdir)


if __name__ == "__main__":
    main()
