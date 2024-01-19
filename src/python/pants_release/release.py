# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import venv
from configparser import ConfigParser
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from functools import total_ordering
from math import ceil
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Sequence, cast

import requests
from packaging.version import Version
from pants_release.common import VERSION_PATH, banner, die, green
from pants_release.git import git, git_rev_parse

from pants.util.contextutil import temporary_dir
from pants.util.memo import memoized_property
from pants.util.strutil import softwrap

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


# Disable the Pants repository-internal internal_plugins.test_lockfile_fixtures plugin because
# otherwise inclusion of that plugin will fail due to its `pytest` import not being included in the pex.
#
# Disable the explorer backend, as that is packaged into a dedicated Python distribution and thus
# not included in the pex either.
DISABLED_BACKENDS_CONFIG = {
    "PANTS_BACKEND_PACKAGES": '-["internal_plugins.test_lockfile_fixtures", "pants_explorer.server"]',
}


@total_ordering
class PackageVersionType(Enum):
    DEV = 0
    PRE = 1
    STABLE = 2

    @classmethod
    def from_version(cls, version: Version) -> PackageVersionType:
        if version.is_devrelease:
            return cls.DEV
        elif version.pre:
            return cls.PRE
        else:
            return cls.STABLE

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, PackageVersionType):
            return NotImplemented
        return self.value < other.value


@dataclass(frozen=True)
class PackageVersion:
    name: str
    version: Version
    size_mb: int
    most_recent_upload_date: date

    @property
    def freshness_key(self) -> tuple[PackageVersionType, date, Version]:
        """A sort key of the type, the creation time, and then (although unlikely to be used) the
        Version.

        Sorts the "stalest" releases first, and the "freshest" releases last.
        """
        return (
            PackageVersionType.from_version(self.version),
            self.most_recent_upload_date,
            self.version,
        )


@total_ordering
class Package:
    def __init__(
        self,
        name: str,
        target: str,
        max_size_mb: int,
        validate: Callable[[str, Path, list[str]], None],
    ) -> None:
        self.name = name
        self.target = target
        self.max_size_mb = max_size_mb
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

    @memoized_property
    def _json_package_data(self) -> dict[str, Any]:
        return cast(dict, requests.get(f"https://pypi.org/pypi/{self.name}/json").json())

    def latest_published_version(self) -> str:
        return cast(str, self._json_package_data["info"]["version"])

    def stale_versions(self) -> Sequence[PackageVersion]:
        def pv(version: str, artifacts: list[dict[str, Any]]) -> PackageVersion | None:
            upload_dates = [
                date.fromisoformat(artifact["upload_time_iso_8601"].split("T")[0])
                for artifact in artifacts
                if "T" in artifact["upload_time_iso_8601"]
            ]
            size_bytes = sum(int(artifact["size"]) for artifact in artifacts)
            size_mb = ceil(size_bytes / 1000000)
            if not upload_dates:
                return None
            return PackageVersion(self.name, Version(version), size_mb, max(upload_dates))

        maybe_versions = [
            pv(version, artifacts)
            for version, artifacts in self._json_package_data["releases"].items()
            if artifacts
        ]
        all_versions_by_freshness_ascending = sorted(
            (pv for pv in maybe_versions if pv), key=lambda pv: pv.freshness_key
        )

        # The stalest artifacts which do fit into our threshold will be considered to be stale.
        # We leave a little more than the max size of an artifact as buffer space in case a new
        # release is particularly large.
        max_artifacts_size_mb = max(pv.size_mb for pv in all_versions_by_freshness_ascending)
        available_mb = self.max_size_mb - (max_artifacts_size_mb * 1.1)

        # Exclude all artifacts which are younger than a threshold, both as a safety measure, and
        # to account for the fact that although we would generally want to delete a dev release
        # before a stable release (etc), that breaks down for very recent releases.
        versions_by_freshness_ascending = []
        for version in all_versions_by_freshness_ascending:
            if version.most_recent_upload_date + MINIMUM_STALE_AGE < date.today():
                # Eligible to be removed.
                versions_by_freshness_ascending.append(version)
                continue
            # Not eligible: must be kept.
            available_mb -= version.size_mb

        # If we have no versions that we can prune, and are already beyond the threshold, it's
        # very likely that a release will fail.
        if not versions_by_freshness_ascending and available_mb < 0:
            print(
                softwrap(
                    f"""
                    There are no stale artifacts to prune (older than {MINIMUM_STALE_AGE}) and
                    we are over capacity: the release is very likely to fail. See
                    [https://github.com/pantsbuild/pants/issues/11614].
                    """
                ),
                file=sys.stderr,
            )

        # Pop versions from the end of the list (the "freshest") while we have remaining space.
        while versions_by_freshness_ascending:
            if versions_by_freshness_ascending[-1].size_mb > available_mb:
                break
            available_mb -= versions_by_freshness_ascending.pop().size_mb

        return versions_by_freshness_ascending


def _pip_args(extra_pip_args: list[str]) -> tuple[str, ...]:
    return (*extra_pip_args, "--quiet", "--no-cache-dir")


def validate_pants_pkg(version: str, venv_bin_dir: Path, extra_pip_args: list[str]) -> None:
    def run_venv_pants(args: list[str]) -> str:
        # When we do (dry-run) testing, we need to run the packaged pants. It doesn't have internal
        # backend plugins embedded (but it does have all other backends): to load only the internal
        # packages, we override the `--python-path` to include them (and to implicitly exclude
        # `src/python`).
        return (
            subprocess.run(
                [
                    venv_bin_dir / "pants",
                    "--no-remote-cache-read",
                    "--no-remote-cache-write",
                    "--no-pantsd",
                    "--pythonpath=['pants-plugins']",
                    *args,
                ],
                check=True,
                stdout=subprocess.PIPE,
                env={
                    **os.environ,
                    **DISABLED_BACKENDS_CONFIG,
                    "NO_SCIE_WARNING": "1",
                },
            )
            .stdout.decode()
            .strip()
        )

    subprocess.run(
        [
            venv_bin_dir / "pip",
            "install",
            *_pip_args(extra_pip_args),
            f"pantsbuild.pants=={version}",
        ],
        check=True,
    )
    outputted_version = run_venv_pants(["--version"])
    if outputted_version != version:
        die(
            softwrap(
                f"""
                Installed version of Pants ({outputted_version}) did not match requested
                version ({version})!
                """
            )
        )
    run_venv_pants(["list", "src::"])


@contextmanager
def install_exercising_namespace_packages(
    venv_bin_dir: Path, *requirements: str, extra_pip_args: list[str]
) -> Iterator[str]:
    """Installs requirements in such a way that the viability of any namespace packages is tested.

    :return: The PYTHONPATH that can be used along with venv_bin_dir / "python" to test the
        installed packages with.
    """
    with temporary_dir() as td:
        tempdir = Path(td)
        wheel_dir = tempdir / "wheels"
        pip = venv_bin_dir / "pip"
        subprocess.run(
            [
                pip,
                "wheel",
                *_pip_args(extra_pip_args),
                "--wheel-dir",
                wheel_dir,
                *requirements,
            ],
            check=True,
        )
        sys_path_entries = []
        for index, wheel in enumerate(wheel_dir.iterdir()):
            sys_path_entry = tempdir / f"entry_{index}"
            subprocess.run(
                [
                    pip,
                    "install",
                    "--quiet",
                    "--no-deps",
                    "--no-index",
                    "--only-binary",
                    ":all:",
                    "--target",
                    sys_path_entry,
                    wheel,
                ],
                check=True,
            )
            sys_path_entries.append(sys_path_entry)
        yield os.pathsep.join(str(entry) for entry in sys_path_entries)


def validate_testutil_pkg(version: str, venv_bin_dir: Path, extra_pip_args: list[str]) -> None:
    with install_exercising_namespace_packages(
        venv_bin_dir, f"pantsbuild.pants.testutil=={version}", extra_pip_args=extra_pip_args
    ) as pythonpath:
        subprocess.run(
            [
                venv_bin_dir / "python",
                "-c",
                softwrap(
                    """
                    import pants.testutil.option_util, pants.testutil.rule_runner,
                    pants.testutil.pants_integration_test
                    """
                ),
            ],
            env={**os.environ, "PYTHONPATH": pythonpath},
            check=True,
        )


# Artifacts created within this time range will never be considered to be stale.
MINIMUM_STALE_AGE = timedelta(days=180)


# NB: This a native wheel. We expect a distinct wheel for each Python version and each
# platform (macOS_x86 x macos_arm x linux).
PANTS_PKG = Package(
    "pantsbuild.pants",
    "src/python/pants:pants-packaged",
    # Increased from the default limit of 20GB via https://github.com/pypa/pypi-support/issues/1376.
    40000,
    validate_pants_pkg,
)
TESTUTIL_PKG = Package(
    "pantsbuild.pants.testutil",
    "src/python/pants/testutil:testutil_wheel",
    20000,
    validate_testutil_pkg,
)
PACKAGES = sorted({PANTS_PKG, TESTUTIL_PKG})


# -----------------------------------------------------------------------------------------------
# Script utils
# -----------------------------------------------------------------------------------------------


class _Constants:
    def __init__(self) -> None:
        self._head_sha = git_rev_parse("HEAD")
        self.pants_stable_version = VERSION_PATH.read_text().strip()

    @property
    def deploy_3rdparty_wheels_path(self) -> str:
        return "wheels/3rdparty"

    @property
    def deploy_pants_wheels_path(self) -> str:
        return "wheels/pantsbuild.pants"

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
    return git_rev_parse("HEAD", abbrev_ref=True)


def get_pgp_key_id() -> str:
    return git("config", "--get", "user.signingkey", check=False)


def get_pgp_program_name() -> str:
    configured_name = git("config", "--get", "gpg.program", check=False)
    return configured_name or "gpg"


def is_cross_platform(wheel_paths: Iterable[Path]) -> bool:
    return not all(wheel.name.endswith("-none-any.whl") for wheel in wheel_paths)


def create_venv(venv_dir: Path) -> Path:
    venv.create(venv_dir, with_pip=True, clear=True, symlinks=True)
    bin_dir = venv_dir / "bin"
    subprocess.run(
        [bin_dir / "pip", "install", "--quiet", "--disable-pip-version-check", "--upgrade", "pip"],
        check=True,
    )
    return bin_dir


@contextmanager
def create_tmp_venv() -> Iterator[Path]:
    """Create a venv and return its bin path.

    Note that the venv is not sourced. You should run bin_path / "pip" and bin_path / "python"
    directly.
    """
    with temporary_dir() as tempdir:
        bin_dir = create_venv(Path(tempdir))
        subprocess.run([(bin_dir / "pip"), "install", "--quiet", "wheel"], check=True)
        yield bin_dir


def create_twine_venv() -> None:
    """Create a venv at CONSTANTS.twine_venv_dir and install Twine."""
    if CONSTANTS.twine_venv_dir.exists():
        shutil.rmtree(CONSTANTS.twine_venv_dir)
    bin_dir = create_venv(CONSTANTS.twine_venv_dir)
    subprocess.run([bin_dir / "pip", "install", "--quiet", "twine"], check=True)


# -----------------------------------------------------------------------------------------------
# Build artifacts
# -----------------------------------------------------------------------------------------------


def build_all_wheels() -> None:
    build_pants_wheels()
    build_3rdparty_wheels()
    install_and_test_packages(
        CONSTANTS.pants_stable_version,
        extra_pip_args=[
            "--only-binary=:all:",
            "-f",
            str(CONSTANTS.deploy_3rdparty_wheel_dir / CONSTANTS.pants_stable_version),
            "-f",
            str(CONSTANTS.deploy_pants_wheel_dir / CONSTANTS.pants_stable_version),
        ],
    )


def install_and_test_packages(version: str, *, extra_pip_args: list[str] | None = None) -> None:
    with create_tmp_venv() as bin_dir:
        for pkg in PACKAGES:
            pip_req = f"{pkg.name}=={version}"
            banner(f"Installing and testing {pip_req}")
            pkg.validate(version, bin_dir, extra_pip_args or [])
            green(f"Tests succeeded for {pip_req}")


def build_pants_wheels() -> None:
    banner(f"Building Pants wheels with Python {CONSTANTS.python_version}")
    version = CONSTANTS.pants_stable_version

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

    try:
        subprocess.run(args, check=True)
    except subprocess.CalledProcessError as e:
        failed_packages = ",".join(package.name for package in PACKAGES)
        failed_targets = " ".join(package.target for package in PACKAGES)
        die(
            softwrap(
                f"""
                Failed to build packages {failed_packages} for {version} with targets
                {failed_targets}.

                {e!r}
                """
            )
        )

    for package in PACKAGES:
        found_wheels = sorted(Path("dist").glob(f"{package}-{version}-*.whl"))
        # NB: For any platform-specific wheels, like pantsbuild.pants, we assume that the
        # top-level `dist` will only have wheels built for the current platform. This
        # should be safe because it is not possible to build native wheels for another
        # platform.
        if not is_cross_platform(found_wheels) and len(found_wheels) > 1:
            die(
                softwrap(
                    f"""
                    Found multiple wheels for {package} in the `dist/` folder, but was
                    expecting only one wheel: {sorted(wheel.name for wheel in found_wheels)}.
                    """
                )
            )
        for wheel in found_wheels:
            wheel_dest = dest / wheel.name
            if not wheel_dest.exists():
                # We use `copy2` to preserve metadata.
                shutil.copy2(wheel, dest)
            # Rewrite to manylinux. See https://www.python.org/dev/peps/pep-0599/.
            # We use manylinux2014 images.
            os.rename(
                wheel_dest,
                wheel_dest.with_name(wheel_dest.name.replace("linux_", "manylinux2014_")),
            )

    green(f"Wrote Pants wheels to {dest}.")

    banner(f"Validating Pants wheels for {CONSTANTS.python_version}.")
    create_twine_venv()
    subprocess.run([CONSTANTS.twine_venv_dir / "bin/twine", "check", dest / "*.whl"], check=True)
    green(f"Validated Pants wheels for {CONSTANTS.python_version}.")


def build_3rdparty_wheels() -> None:
    banner(f"Building 3rdparty wheels with Python {CONSTANTS.python_version}")
    dest = CONSTANTS.deploy_3rdparty_wheel_dir / CONSTANTS.pants_stable_version
    pkg_tgts = [pkg.target for pkg in PACKAGES]
    with create_tmp_venv() as bin_dir:
        deps = (
            subprocess.run(
                [
                    "./pants",
                    "--concurrent",
                    "dependencies",
                    "--transitive",
                    *pkg_tgts,
                ],
                stdout=subprocess.PIPE,
                check=True,
            )
            .stdout.decode()
            .strip()
            .splitlines()
        )
        python_requirements = (
            subprocess.run(
                [
                    "./pants",
                    "--concurrent",
                    "list",
                    "--filter-target-type=python_requirement",
                    *deps,
                ],
                stdout=subprocess.PIPE,
                check=True,
            )
            .stdout.decode()
            .strip()
            .splitlines()
        )
        if not python_requirements:
            die(
                softwrap(
                    f"""
                    No 3rd-party dependencies detected for {pkg_tgts}. Is `./pants dependencies`
                    broken?
                    """
                )
            )
        reqs = itertools.chain.from_iterable(
            obj["requirements"]
            for obj in json.loads(
                subprocess.run(
                    [
                        "./pants",
                        "--concurrent",
                        "peek",
                        *python_requirements,
                    ],
                    stdout=subprocess.PIPE,
                    check=True,
                ).stdout
            )
        )
        subprocess.run(
            [bin_dir / "pip", "wheel", f"--wheel-dir={dest}", *reqs],
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
        Path(CONSTANTS.deploy_dir) / "bin" / "fs_util" / current_os / CONSTANTS.pants_stable_version
    )
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        f"src/rust/engine/target/{'release' if release_mode else 'debug'}/fs_util",
        dest_dir,
    )
    green(f"Built fs_util at {dest_dir / 'fs_util'}.")


# -----------------------------------------------------------------------------------------------
# Begin a release by pushing a release tag
# -----------------------------------------------------------------------------------------------


def tag_release() -> None:
    banner("Tagging release")

    check_clean_git_branch()
    check_pgp()

    prompt_artifact_freshness()

    run_tag_release()
    banner("Successfully tagged release")


def check_clean_git_branch() -> None:
    banner("Checking for a clean Git branch")
    git_status = git("status", "--porcelain")
    if git_status:
        die(
            softwrap(
                """
                Uncommitted changes detected when running `git status`. You must be on a clean branch
                to release.
                """
            )
        )
    valid_branch_pattern = r"^(main)|([0-9]+\.[0-9]+\.x)$"
    git_branch = get_git_branch()
    if not re.match(valid_branch_pattern, git_branch):
        die(
            softwrap(
                f"""
                On an invalid branch. You must either be on `main` or a release branch like
                `2.4.x`. Detected: {git_branch}
                """
            )
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
            softwrap(
                """
                Please configure the key you intend to use. See
                https://www.pantsbuild.org/docs/release-process.
                """
            )
        )


def run_tag_release() -> None:
    tag_name = f"release_{CONSTANTS.pants_stable_version}"
    git(
        "tag",
        "-f",
        f"--local-user={get_pgp_key_id()}",
        "-m",
        f"pantsbuild.pants release {CONSTANTS.pants_stable_version}",
        tag_name,
        capture_stdout=False,
    )
    git("push", "-f", "git@github.com:pantsbuild/pants.git", tag_name, capture_stdout=False)


def upload_wheels_via_twine() -> None:
    subprocess.run(
        [
            str(CONSTANTS.twine_venv_dir / "bin/twine"),
            "upload",
            "--skip-existing",  # Makes the upload idempotent.
            str(CONSTANTS.deploy_pants_wheel_dir / CONSTANTS.pants_stable_version / "*.whl"),
        ],
        check=True,
    )


def prompt_artifact_freshness() -> None:
    stale_versions = [
        stale_version for package in PACKAGES for stale_version in package.stale_versions()
    ]
    if stale_versions:
        print("\n".join(f"Stale:\n  {sv}" for sv in stale_versions))
        input(
            softwrap(
                """
                To ensure that there is adequate storage for new artifacts, the stale release
                artifacts listed above should be deleted via [https://pypi.org/]'s UI.

                If you have any concerns about the listed artifacts, or do not have access to
                delete them yourself, please raise an issue in #development Slack or on
                [https://github.com/pantsbuild/pants/issues/11614].

                Press enter when you have deleted the listed artifacts:
                """
            )
        )
    else:
        print("No stale artifacts detected.")


# -----------------------------------------------------------------------------------------------
# Test release
# -----------------------------------------------------------------------------------------------


def test_release() -> None:
    banner("Installing and testing the latest released packages")
    smoke_test_install_and_version(CONSTANTS.pants_stable_version)
    banner("Successfully ran a smoke test of the released packages")


def smoke_test_install_and_version(version: str) -> None:
    """Do two tests to confirm that both sets of artifacts (PEXes for running normally, and wheels
    for plugins) have ended up somewhere plausible, to catch major infra failures."""
    with temporary_dir() as dir_:
        dir = Path(dir_)
        (dir / "pants.toml").write_text(
            f"""
            [GLOBAL]
            pants_version = "{version}"

            backend_packages = [
                "pants.backend.python",
                "pants.backend.plugin_development",
            ]

            [python]
            interpreter_constraints = ["==3.9.*"]
            enable_resolves = true
            """
        )

        # First: test that running pants normally reports the expected version:
        result = subprocess.run(
            ["pants", "version"],
            cwd=dir,
            check=True,
            stdout=subprocess.PIPE,
        )
        printed_version = result.stdout.decode().strip()
        if printed_version != version:
            die(f"Failed to confirm pants version, expected {version!r}, got {printed_version!r}")

        # Second: test that the wheels can be installed/imported (for plugins):
        (dir / "BUILD").write_text("python_sources(name='py'); pants_requirements(name='pants')")
        # We confirm the version from the main wheel, but only check that the testutil code can
        # be imported at all.
        (dir / "example.py").write_text(
            "from pants import version, testutil; print(version.VERSION)"
        )
        result = subprocess.run(
            ["pants", "generate-lockfiles"],
            cwd=dir,
            check=True,
        )
        result = subprocess.run(
            ["pants", "run", "example.py"],
            cwd=dir,
            check=True,
            stdout=subprocess.PIPE,
        )
        wheel_version = result.stdout.decode().strip()
        if printed_version != version:
            die(f"Failed to confirm wheel version, expected {version!r}, got {wheel_version!r}")


# -----------------------------------------------------------------------------------------------
# main()
# -----------------------------------------------------------------------------------------------


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("tag-release")

    fetch_and_stabilize = subparsers.add_parser("fetch-and-stabilize")
    fetch_and_stabilize.add_argument(
        "--dest",
        help="A destination directory to put stabilized wheels in.",
    )

    subparsers.add_parser("test-release")
    subparsers.add_parser("build-wheels")
    subparsers.add_parser("build-fs-util")
    return parser


def main() -> None:
    args = create_parser().parse_args()
    if args.command == "tag-release":
        tag_release()
    if args.command == "test-release":
        test_release()
    if args.command == "build-wheels":
        build_all_wheels()
    if args.command == "build-fs-util":
        build_fs_util()


if __name__ == "__main__":
    main()
