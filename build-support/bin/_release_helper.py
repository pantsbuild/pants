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
from typing import Any, Callable, Iterable, Iterator, NamedTuple, Sequence, cast
from urllib.parse import quote_plus
from xml.etree import ElementTree

import requests
from common import banner, die, green
from packaging.version import Version
from reversion import reversion

from pants.util.contextutil import temporary_dir, temporary_file_path
from pants.util.memo import memoized_property
from pants.util.strutil import softwrap, strip_prefix

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
    "PANTS_BACKEND_PACKAGES": '-["internal_plugins.test_lockfile_fixtures", "pants.explorer.server"]',
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
            softwrap(
                f"""
                Could not find a requirement starting with `pex==` in
                3rdparty/python/requirements.txt: {repr(exc)}
                """
            )
        )

    with temporary_dir() as tempdir:
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
                softwrap(
                    f"""
                    Failed to build packages {failed_packages} for {version} with targets
                    {failed_targets}.

                    {e!r}
                    """
                )
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
                    softwrap(
                        f"""
                        Found multiple wheels for {package} in the `dist/` folder, but was
                        expecting only one wheel: {sorted(wheel.name for wheel in found_wheels)}.
                        """
                    )
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
    stable = os.environ.get("PANTS_PEX_RELEASE", "") == "STABLE"
    if fetch:
        # TODO: Support macOS on ARM64.
        extra_pex_args = [
            "--python-shebang",
            "/usr/bin/env python",
            *(
                f"--platform={plat}-{abi}"
                for plat in ("linux_x86_64", "macosx_11.0_x86_64")
                for abi in ("cp-37-m", "cp-38-cp38", "cp-39-cp39")
            ),
        ]
        pex_name = f"pants.{CONSTANTS.pants_unstable_version}.pex"
        banner(f"Building {pex_name} by fetching wheels.")
    else:
        # TODO: Support macOS on ARM64. Will require qualifying the pex name with the arch.
        major, minor = sys.version_info[:2]
        extra_pex_args = [
            f"--interpreter-constraint=CPython=={major}.{minor}.*",
            f"--python={sys.executable}",
        ]
        plat = os.uname()[0].lower()
        py = f"cp{major}{minor}"
        pex_name = f"pants.{CONSTANTS.pants_unstable_version}.{plat}-{py}.pex"
        banner(f"Building {pex_name} by building wheels.")

    if CONSTANTS.deploy_dir.exists():
        shutil.rmtree(CONSTANTS.deploy_dir)
    CONSTANTS.deploy_dir.mkdir(parents=True)

    if fetch:
        fetch_prebuilt_wheels(CONSTANTS.deploy_dir, include_3rdparty=True)
        check_pants_wheels_present(CONSTANTS.deploy_dir)
        if stable:
            reversion_prebuilt_wheels()
    else:
        build_pants_wheels()
        build_3rdparty_wheels()

    # We need to both run Pex and the Pants PEX we build with it with clean environments since we
    # ourselves may be running via `./pants run ...` which injects confounding environment variables
    # like PEX_EXTRA_SYS_PATH, PEX_PATH and PEX_ROOT that need not or should not apply to these
    # sub-processes.
    env = {k: v for k, v in os.environ.items() if not k.startswith("PEX_")}

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
                "--venv",
            ],
            env=env,
            check=True,
        )

    if stable:
        stable_dest = CONSTANTS.deploy_dir / "pex" / f"pants.{CONSTANTS.pants_stable_version}.pex"
        stable_dest.parent.mkdir(parents=True, exist_ok=True)
        dest.rename(stable_dest)
        dest = stable_dest
    green(f"Built {dest}")


# -----------------------------------------------------------------------------------------------
# Publish
# -----------------------------------------------------------------------------------------------


def publish() -> None:
    banner("Releasing to PyPI and GitHub")
    # Check prereqs.
    check_clean_git_branch()
    prompt_artifact_freshness()
    check_pgp()
    check_gh_cli()

    # Fetch and validate prebuilt wheels.
    if CONSTANTS.deploy_pants_wheel_dir.exists():
        shutil.rmtree(CONSTANTS.deploy_pants_wheel_dir)
    fetch_prebuilt_wheels(CONSTANTS.deploy_dir, include_3rdparty=True)
    check_pants_wheels_present(CONSTANTS.deploy_dir)
    reversion_prebuilt_wheels()

    # Release.
    create_twine_venv()
    upload_wheels_via_twine()
    tag_release()
    do_github_release()
    banner("Successfully released to PyPI and GitHub")
    prompt_to_generate_docs()


def do_github_release() -> None:
    version = CONSTANTS.pants_stable_version
    is_prerelease = PackageVersionType.from_version(Version(version)) != PackageVersionType.STABLE

    def get_notes() -> str:
        maj, min = version.split(".")[:2]
        notes_path = Path("src/python/pants/notes", maj).with_suffix(f".{min}.x.md")
        notes_contents = notes_path.read_text()
        for section in notes_contents.split("\n## "):
            if section.startswith(version):
                section = section.replace("##", "#")
                return section.split("\n", 2)[-1]
        assert False

    with temporary_file_path() as notes_file:
        Path(notes_file).write_text(get_notes())

        subprocess.run(
            [
                "gh",
                "release",
                "create",
                f"release_{version}",
                "--notes-file",
                notes_file,
                "--title",
                version,
                "--draft",
                *(["--prerelease"] if is_prerelease else []),
            ],
            check=True,
        )

    stable_wheel_dir = CONSTANTS.deploy_pants_wheel_dir / version
    for whl in stable_wheel_dir.glob("*.whl"):
        subprocess.run(
            ["gh", "release", "upload", f"release_{version}", f"{whl}#{whl.name}"],
            check=True,
        )

    def build_local_pex(pex_name, platform):
        with download_pex_bin() as pex_bin:
            subprocess.run(
                [
                    sys.executable,
                    str(pex_bin),
                    "--disable-cache",
                    "--python-shebang",
                    "/usr/bin/env python",
                    "-o",
                    pex_name,
                    "-f",
                    str(CONSTANTS.deploy_pants_wheel_dir / CONSTANTS.pants_unstable_version),
                    "-f",
                    str(CONSTANTS.deploy_3rdparty_wheel_dir / CONSTANTS.pants_unstable_version),
                    f"pantsbuild.pants=={version}",
                    "--no-build",
                    "--no-pypi",
                    "--disable-cache",
                    "--no-strip-pex-env",
                    "--console-script=pants",
                    "--venv",
                    f"--platform={platform}-cp-39-cp39",
                ],
                check=True,
            )
        subprocess.run(
            ["gh", "release", "upload", f"release_{version}", pex_name],
            check=True,
        )

    build_local_pex(f"pants.{version}-cp39-darwin_arm64.pex", "macosx-11.0-arm64")
    build_local_pex(f"pants.{version}-cp39-darwin_x86_64.pex", "macosx-10.15-x86_64")
    build_local_pex(f"pants.{version}-cp39-linux_aarch64.pex", "linux_aarch64")
    build_local_pex(f"pants.{version}-cp39-linux_x86_64.pex ", "linux_x86_64")

    subprocess.run(["gh", "release", "edit", f"release_{version}", "--draft=false"], check=True)


def check_gh_cli() -> None:
    banner("Checking for the GH CLI")
    result = subprocess.run(["gh", "auth", "status"], stdout=subprocess.PIPE, check=False)
    if result.returncode:
        die("Please install the GH CLI: https://cli.github.com/ and run `gh auth login`.")


def check_clean_git_branch() -> None:
    banner("Checking for a clean Git branch")
    git_status = (
        subprocess.run(["git", "status", "--porcelain"], stdout=subprocess.PIPE, check=True)
        .stdout.decode()
        .strip()
    )
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


def reversion_prebuilt_wheels() -> None:
    # First, rewrite to manylinux. See https://www.python.org/dev/peps/pep-0599/. We use
    # manylinux2014 images.
    source_platform = "linux_"
    dest_platform = "manylinux2014_"
    unstable_wheel_dir = CONSTANTS.deploy_pants_wheel_dir / CONSTANTS.pants_unstable_version
    for whl in unstable_wheel_dir.glob(f"*{source_platform}*.whl"):
        whl.rename(str(whl).replace(source_platform, dest_platform))

    # Now, reversion to use the STABLE_VERSION.
    stable_wheel_dir = CONSTANTS.deploy_pants_wheel_dir / CONSTANTS.pants_stable_version
    stable_wheel_dir.mkdir(parents=True, exist_ok=True)
    for whl in unstable_wheel_dir.glob("*.whl"):
        reversion(
            whl_file=str(whl),
            dest_dir=str(stable_wheel_dir),
            target_version=CONSTANTS.pants_stable_version,
            extra_globs=["pants/_version/VERSION"],
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


def prompt_to_generate_docs() -> None:
    has_docs_access = input(
        softwrap(
            """
            The docs now need to be regenerated. Do you already have editing access to
            readme.com? [Y/n]:
            """
        )
    )
    # This URL will work regardless of the current version, so long as we don't delete 2.5 from
    # the docs.
    api_key_url = "https://dash.readme.com/project/pants/v2.5/api-key"
    docs_cmd = "./pants run build-support/bin/generate_docs.py -- --sync --api-key <key>"
    if has_docs_access and has_docs_access.lower() != "y":
        print(
            softwrap(
                f"""
                Please ask in the #maintainers Slack channel to be added to Readme.com. Please
                enable two-factor authentication!

                Then go to {api_key_url} to find your API key. Run this command:

                    {docs_cmd}

                (If you are not comfortable getting permissions, you can ask another maintainer to
                run this script in the #maintainers Slack.)
                """
            )
        )
    else:
        print(
            softwrap(
                f"""
                Please go to {api_key_url} to find your API key. Then, run this command:

                    {docs_cmd}
            """
            )
        )


# -----------------------------------------------------------------------------------------------
# Test release
# -----------------------------------------------------------------------------------------------


def test_release() -> None:
    banner("Installing and testing the latest released packages")
    install_and_test_packages(CONSTANTS.pants_stable_version)
    banner("Successfully installed and tested the latest released packages")


def install_and_test_packages(version: str, *, extra_pip_args: list[str] | None = None) -> None:
    with create_tmp_venv() as bin_dir:
        for pkg in PACKAGES:
            pip_req = f"{pkg.name}=={version}"
            banner(f"Installing and testing {pip_req}")
            pkg.validate(version, bin_dir, extra_pip_args or [])
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
        if is_cross_platform(local_files) and len(local_files) != 10:
            formatted_local_files = "\n    ".join(sorted(f.name for f in local_files))
            missing_packages.append(
                softwrap(
                    f"""
                    {package.name}. Expected 10 wheels ({{cp37m, cp38, cp39}} x
                    {{macosx10.15-x86_64, macosx11-x86_64, linux-x86_64}} + cp39-macosx-arm64),
                    but found {len(local_files)}:\n    {formatted_local_files}
                    """
                )
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
    subparsers.add_parser("test-release")
    subparsers.add_parser("build-wheels")
    subparsers.add_parser("build-fs-util")
    subparsers.add_parser("build-local-pex")
    subparsers.add_parser("build-universal-pex")
    subparsers.add_parser("validate-roles")
    subparsers.add_parser("validate-freshness")
    subparsers.add_parser("list-prebuilt-wheels")
    subparsers.add_parser("check-pants-wheels")
    return parser


def main() -> None:
    args = create_parser().parse_args()
    if args.command == "publish":
        publish()
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
    if args.command == "validate-freshness":
        prompt_artifact_freshness()
    if args.command == "list-prebuilt-wheels":
        list_prebuilt_wheels()
    if args.command == "check-pants-wheels":
        with temporary_dir() as tempdir:
            fetch_prebuilt_wheels(tempdir, include_3rdparty=False)
            check_pants_wheels_present(tempdir)


if __name__ == "__main__":
    main()
