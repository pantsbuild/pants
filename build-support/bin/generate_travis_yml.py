# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from enum import Enum
from textwrap import dedent
from typing import Dict, List, Optional

import yaml


HEADER = dedent("""\
  # GENERATED, DO NOT EDIT!
  # To change, edit `build-support/bin/generate_travis_yml.py` and run:
  # ./pants --quiet run build-support/bin:generate_travis_yml > .travis.yml
  """)

# ----------------------------------------------------------------------
# Stages
# ----------------------------------------------------------------------

class Stage(Enum):
  bootstrap = "Bootstrap Pants"
  bootstrap_cron = "Bootstrap Pants (Cron)"
  test = "Test Pants"
  test_cron = "Test Pants (Cron)"
  build_stable = "Deploy Pants Pex"
  build_unstable = "Deploy Pants Pex Unstable"

  def condition(self) -> str:
    is_cron = "type = cron"
    is_not_cron = "type != cron"
    return {
      self.bootstrap: is_not_cron,
      self.bootstrap_cron: is_cron,
      self.test: is_not_cron,
      self.test_cron: is_cron,
      self.build_stable: r"tag IS present AND tag =~ ^release_.*$",
      self.build_unstable: r"tag IS NOT present AND type NOT IN (pull_request, cron)"
    }[self]

  @classmethod
  def all_entries(cls) -> List[Dict[str, str]]:
    return [{"name": stage.value, "if": stage.condition()} for stage in Stage]

# ----------------------------------------------------------------------
# Env vars
# ----------------------------------------------------------------------

GLOBAL_ENV_VARS = [
  'PANTS_CONFIG_FILES="${TRAVIS_BUILD_DIR}/pants.travis-ci.ini"',
  'LC_ALL="en_US.UTF-8"',
  'BOOTSTRAPPED_PEX_BUCKET=ci-public.pantsbuild.org',
  'BOOTSTRAPPED_PEX_KEY_PREFIX=${TRAVIS_BUILD_NUMBER}/${TRAVIS_BUILD_ID}/pants.pex',
  'BOOTSTRAPPED_PEX_URL_PREFIX=s3://${BOOTSTRAPPED_PEX_BUCKET}/${BOOTSTRAPPED_PEX_KEY_PREFIX}',
  'PYENV_PY27_VERSION=2.7.15',
  'PYENV_PY36_VERSION=3.6.8',
  'PYENV_PY37_VERSION=3.7.2',
  # NB: We must set `PYENV_ROOT` on macOS for Pyenv to work properly. However, on Linux, we must not
  # override the default value because Linux pre-installs Python via Pyenv and we must keep their
  # $PYENV_ROOT for this to still work.
  'PYENV_ROOT="${PYENV_ROOT:-${HOME}/.pants_pyenv}"',
  'PATH="${PYENV_ROOT}/shims:${PATH}"',
  'AWS_CLI_ROOT="${HOME}/.aws_cli"',
  # NB: We use this verbose name so that AWS does not pick up the env var $AWS_ACCESS_KEY_ID on
  # pull request builds. We only want this value to be populated on branch builds. Users of this
  # env var (i.e. `deploy_to_s3.py`) are expected to re-export the env var as $AWS_ACCESS_KEY_ID.
  'AWS_ACCESS_KEY_ID__TO_BE_REEXPORTED_ON_DEPLOYS=AKIAV6A6G7RQWPRUWIXR',
  # This stores the encrypted AWS secret access key with the env var AWS_SECRET_ACCESS_KEY.
  # Travis converts it back into its original decrypted value when ran in CI, per
  # https://docs.travis-ci.com/user/environment-variables#defining-encrypted-variables-in-travisyml.
  {"secure": "hFVAQGLVkexzTd3f9NF+JoG1dE+CPICKqOcdvQYv8+YB2rwwqu0/J6MnqKUZSmec4AM4ZvyPUBIHnSw8aMJysYs+GZ6iG/8ZRRmdbmo2WBPbSZ+ThRZxx/F6AjmovUmf8Zt366ZAZXpc9NHKREkTUGl6UL7FFe9+ouVnb90asdw="},
  'RUST_BACKTRACE="all"',
]

# ----------------------------------------------------------------------
# Python versions
# ----------------------------------------------------------------------

class PythonVersion(Enum):
  py36 = "py36"
  py37 = "py37"

  def __str__(self) -> str:
    return str(self.value)

  @property
  def number(self) -> int:
    return {self.py36: 36, self.py37: 37}[self]

  @property
  def decimal(self) -> float:
    return {self.py36: 3.6, self.py37: 3.7}[self]

  @property
  def is_py36(self) -> bool:
    return self == PythonVersion.py36

  @property
  def is_py37(self) -> bool:
    return self == PythonVersion.py37

  def default_stage(self, *, is_bootstrap: bool = False) -> Stage:
    if is_bootstrap:
      return {self.py36: Stage.bootstrap, self.py37: Stage.bootstrap_cron}[self]
    return {self.py36: Stage.test, self.py37: Stage.test_cron}[self]


# ----------------------------------------------------------------------
# AWS
# ----------------------------------------------------------------------

# We use AWS S3 to avoid unnecessary work in CI. Specifically, the bootstrap
# shards create a pants.pex, and then upload it to S3 for all of the test
# shards to pull down.

AWS_GET_PANTS_PEX_COMMAND = ' '.join([
  "./build-support/bin/get_ci_bootstrapped_pants_pex.sh",
  '${BOOTSTRAPPED_PEX_BUCKET}',
  "${BOOTSTRAPPED_PEX_KEY_PREFIX}.${BOOTSTRAPPED_PEX_KEY_SUFFIX}",
])

AWS_DEPLOY_PANTS_PEX_COMMAND = ' '.join([
  "aws", "--no-sign-request", "--region", "us-east-1", "s3", "cp",
  "${TRAVIS_BUILD_DIR}/pants.pex", "${BOOTSTRAPPED_PEX_URL_PREFIX}.${BOOTSTRAPPED_PEX_KEY_SUFFIX}"
])

# ----------------------------------------------------------------------
# Docker
# ----------------------------------------------------------------------

def docker_build_travis_ci_image(*, python_version: PythonVersion) -> str:
  centos_version = 6 if python_version.is_py36 else 7
  return ' '.join([
    "docker", "build", "--rm", "-t", "travis_ci",
    "--build-arg", f'"BASE_IMAGE=pantsbuild/centos{centos_version}:latest"',
    "--build-arg", '"TRAVIS_USER=$(id -un)"',
    "--build-arg", '"TRAVIS_UID=$(id -u)"',
    "--build-arg", '"TRAVIS_GROUP=$(id -gn)"',
    "--build-arg", '"TRAVIS_GID=$(id -g)"',
    "build-support/docker/travis_ci/"
  ])


def docker_run_travis_ci_image(command: str) -> str:
  return ' '.join([
    "docker", "run", "--rm", "-t", "-v", '"${HOME}:/travis/home"',
    "-v", '"${TRAVIS_BUILD_DIR}:/travis/workdir"', "travis_ci:latest",
    "sh", "-c", f'"{command}"'
  ])


# ----------------------------------------------------------------------
# Caches
# ----------------------------------------------------------------------

# The default timeout is 180 seconds, and our larger cache uploads exceed this.
# TODO: Figure out why we have such large caches (2-7GB) and try to trim them.
_cache_timeout = 500
_cache_common_directories = ['${AWS_CLI_ROOT}', '${PYENV_ROOT}']
# Ensure permissions to do the below removals, which happen with or without caching enabled.
_cache_set_required_permissions = 'sudo chown -R travis:travis "${HOME}" "${TRAVIS_BUILD_DIR}"'

CACHE_NATIVE_ENGINE = {
  "before_cache": [
    _cache_set_required_permissions,
    # Kill all Python bytecode in our cached venvs. Some files appear to
    # get bytecode compiled in non-yet-understood circumstances leading to
    # a full cache re-pack due to new bytecode files.
    'find build-support -name "*.py[co]" -delete',
  ],
  "cache": {
    "timeout": _cache_timeout,
    "directories": _cache_common_directories + [
      '${HOME}/.cache/pants/rust/cargo',
      'build-support/virtualenvs',
      'src/rust/engine/target',
    ]
  }
}

CACHE_PANTS_RUN = {
  "before_cache": [
    _cache_set_required_permissions,
    # The `ivydata-*.properties` & root level `*.{properties,xml}` files'
    # effect on resolution time is in the noise, but they are
    # re-timestamped in internal comments and fields on each run and this
    # leads to travis-ci cache thrash.  Kill these files before the cache
    # check to avoid un-needed cache re-packing and re-upload (a ~100s
    # operation).
    'find ${HOME}/.ivy2/pants -type f -name "ivydata-*.properties" -delete',
    'rm -f ${HOME}/.ivy2/pants/*.{css,properties,xml,xsl}',
    # We have several tests that do local file:// url resolves for
    # com.example artifacts, these disrupt the cache but are fast since
    # they're resolved from local files when omitted from the cache.
    'rm -rf ${HOME}/.ivy2/pants/com.example',
    # Render a summary to assist with further tuning the cache.
    'du -m -d2 ${HOME}/.cache/pants | sort -r -n',
  ],
  "cache": {
    "timeout": _cache_timeout,
    "directories": _cache_common_directories + [
      # We include the lmdb_store to include a local process cache, so that hopefully we don't
      # need to re-run processes (particularly tests) which have already run.
      # TODO(#8041): Prune this directory before storing the cache.
      '${HOME}/.cache/pants/lmdb_store',
      '${HOME}/.cache/pants/tools',
      '${HOME}/.cache/pants/zinc',
      '${HOME}/.ivy2/pants',
      # TODO(John Sirois): Update this to ~/.npm/pants when pants starts using its own isolated
      #  cache: https://github.com/pantsbuild/pants/issues/2485
      '${HOME}/.npm',
    ]
  }
}

# ----------------------------------------------------------------------
# OS setups
# ----------------------------------------------------------------------

class Platform(Enum):
  linux = "linux"
  osx = "osx"

  def __str__(self) -> str:
    return str(self.value)


def _linux_before_install(include_test_config: bool = True, install_travis_wait: bool = False) -> List[str]:
  commands = [
    "./build-support/bin/install_aws_cli_for_ci.sh",
    # TODO(John Sirois): Get rid of this in favor of explicitly adding pyenv versions to the PATH:
    #   https://github.com/pantsbuild/pants/issues/7601
    "pyenv global 2.7.15 3.6.7 3.7.1",
  ]
  if install_travis_wait:
    commands.extend([
      (
        'wget -qO- "https://github.com/crazy-max/travis-wait-enhanced/releases/download/v0.2.1/travis-wait-enhanced_0.2'
        '.1_linux_x86_64.tar.gz" | tar -zxvf - travis-wait-enhanced'
      ),
      "mv travis-wait-enhanced /home/travis/bin/",
    ])

  if include_test_config:
    return [
      'PATH="/usr/lib/jvm/java-8-openjdk-amd64/jre/bin":$PATH',
      'JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64',
      'sudo sysctl fs.inotify.max_user_watches=524288',
    ] + commands
  return commands


def linux_shard(
  *,
  load_test_config: bool = True,
  python_version: PythonVersion = PythonVersion.py36,
  use_docker: bool = False,
  install_travis_wait: bool = False,
) -> Dict:
  if load_test_config and python_version is None:
    raise ValueError("Must provide the Python version if using a test config.")
  setup = {
    "os": "linux",
    "dist": "xenial",
    "sudo": "required",
    "python": ["2.7", "3.6", "3.7"],
    "addons": {"apt": {"packages": [
      "lib32stdc++6",
      "lib32z1",
      "lib32z1-dev",
      "gcc-multilib",
      "python-dev",
      "openssl",
      "libssl-dev",
      "jq",
      "unzip",
      "shellcheck",
    ]}},
    "language": "python",
    "before_install": _linux_before_install(include_test_config=load_test_config, install_travis_wait=install_travis_wait),
    "after_failure": ["./build-support/bin/ci-failure.sh"],
    "stage": python_version.default_stage().value,
    "env": [],
  }
  if load_test_config:
    setup["before_script"] = [AWS_GET_PANTS_PEX_COMMAND]
    setup["env"] = [
      f"BOOTSTRAPPED_PEX_KEY_SUFFIX=py{python_version.number}.linux",
      "PANTS_REMOTE_CA_CERTS_PATH=/usr/lib/google-cloud-sdk/lib/third_party/grpc/_cython/_credentials/roots.pem",
    ]
    setup = {**setup, **CACHE_PANTS_RUN}
    if python_version.is_py37:
      # 3.7.2 for Linux uses the new C++ ABI, which may be an error.
      setup["env"].append('PANTS_NATIVE_BUILD_STEP_CPP_COMPILE_SETTINGS_DEFAULT_COMPILER_OPTION_SETS="[]"')
  if use_docker:
    setup["services"] = ["docker"]
    setup["before_script"] = setup.get("before_script", []) + ["ulimit -c unlimited"]
  return setup


def linux_fuse_shard() -> Dict:
  return {
    "os": "linux",
    "dist": "xenial",
    "sudo": "required",
    "python": ["2.7", "3.6", "3.7"],
    "before_install": _linux_before_install() + [
      "sudo apt-get install -y pkg-config fuse libfuse-dev",
      "sudo modprobe fuse",
      "sudo chmod 666 /dev/fuse",
      "sudo chown root:$USER /etc/fuse.conf",
    ]
  }


def _osx_env() -> List[str]:
  return [
    'PATH="/usr/local/opt/openssl/bin:${PATH}"',
    'LDFLAGS="-L/usr/local/opt/openssl/lib"',
    'CPPFLAGS="-I/usr/local/opt/openssl/include"',
  ]


def _osx_env_with_pyenv(python_version: PythonVersion) -> List[str]:
  return [
    *_osx_env(),
    'PATH="${PYENV_ROOT}/versions/${PYENV_PY27_VERSION}/bin:${PATH}"',
    f'PATH="${{PYENV_ROOT}}/versions/${{PYENV_PY{python_version.number}_VERSION}}/bin:${{PATH}}"',
  ]


def osx_shard(
  *,
  load_test_config: bool = True,
  python_version: PythonVersion = PythonVersion.py36,
  osx_image: Optional[str] = None,
) -> Dict:
  setup = {
    "os": "osx",
    "language": "generic",
    "before_script": [
      "ulimit -c unlimited",
      "ulimit -n 8192",
    ],
    "before_install": [
      'curl -L https://github.com/stedolan/jq/releases/download/jq-1.5/jq-osx-amd64 -o /usr/local/bin/jq',
      'chmod 755 /usr/local/bin/jq',
      './build-support/bin/install_aws_cli_for_ci.sh',
      f'./build-support/bin/install_python_for_ci.sh "${{PYENV_PY27_VERSION}}" "${{PYENV_PY{python_version.number}_VERSION}}"',
    ],
    "env": _osx_env_with_pyenv(python_version),
    "stage": python_version.default_stage().value
  }
  if osx_image is not None:
    setup["osx_image"] = osx_image
  if load_test_config:
    setup["before_script"].append(AWS_GET_PANTS_PEX_COMMAND)
    setup["env"].append(f"BOOTSTRAPPED_PEX_KEY_SUFFIX=py{python_version.number}.osx")
  return setup

# ----------------------------------------------------------------------
# Bootstrap engine
# ----------------------------------------------------------------------

def _bootstrap_command(*, python_version: PythonVersion) -> List[str]:
  # Note that for each platform, we have the Python 3.6 shard also create fs_util and upload to S3,
  # to take advantage of the Rust code built during bootstrapping. We use the Python 3.6 shard, as
  # it runs during both daily and nightly CI. This requires setting PREPARE_DEPLOY=1.
  command = [f'./build-support/bin/ci.py --bootstrap --python-version {python_version.decimal}']
  if python_version.is_py36:
    command.append('./build-support/bin/release.sh -f')
  return command


def _bootstrap_env(*, python_version: PythonVersion, platform: Platform) -> List[str]:
  env = [
    f'CACHE_NAME=bootstrap.{platform}.py{python_version.number}',
    f'BOOTSTRAPPED_PEX_KEY_SUFFIX=py{python_version.number}.{platform}'
  ]
  if python_version.is_py36:
    env.append("PREPARE_DEPLOY=1")
  return env


def bootstrap_linux(python_version: PythonVersion) -> Dict:
  command = " && ".join(_bootstrap_command(python_version=python_version))
  shard = {
    **CACHE_NATIVE_ENGINE,
    **linux_shard(load_test_config=False, python_version=python_version, use_docker=True),
    "name": f"Build Linux native engine and pants.pex (Python {python_version.decimal})",
    "stage": python_version.default_stage(is_bootstrap=True).value,
    "script": [
      docker_build_travis_ci_image(python_version=python_version),
      docker_run_travis_ci_image(command),
      AWS_DEPLOY_PANTS_PEX_COMMAND,
    ]
  }
  shard["env"] = shard.get("env", []) + _bootstrap_env(python_version=python_version, platform=Platform.linux)
  return shard


def bootstrap_osx(python_version: PythonVersion) -> Dict:
  shard = {
    **CACHE_NATIVE_ENGINE,
    # We request the oldest image we can (corresponding to OSX 10.11) for maximum compatibility.
    # We use 10.11 as a minimum to avoid https://github.com/rust-lang/regex/issues/489.
    # See: https://docs.travis-ci.com/user/reference/osx/#OS-X-Version
    **osx_shard(load_test_config=False, python_version=python_version, osx_image="xcode8"),
    "name": f"Build OSX native engine and pants.pex (Python {python_version.decimal})",
    "after_failure": ["./build-support/bin/ci-failure.sh"],
    "stage": python_version.default_stage(is_bootstrap=True).value,
    "script": _bootstrap_command(python_version=python_version) + [AWS_DEPLOY_PANTS_PEX_COMMAND]
  }
  shard["env"] = shard.get("env", []) + _bootstrap_env(python_version=python_version, platform=Platform.osx)
  return shard

# ----------------------------------------------------------------------
# Lint
# ----------------------------------------------------------------------

def lint(python_version: PythonVersion) -> Dict:
  shard = {
    **linux_shard(python_version=python_version),
    "name": f"Self-checks and lint (Python {python_version.decimal})",
    "script": [
      f"./build-support/bin/ci.py --githooks --sanity-checks --doc-gen --lint --python-version {python_version.decimal}"
    ]
  }
  shard["env"] = shard.get("env", []) + [f"CACHE_NAME=lint.py{python_version.number}"]
  return shard

# -------------------------------------------------------------------------
# Rust lints
# -------------------------------------------------------------------------

def clippy() -> Dict:
  return {
    **CACHE_NATIVE_ENGINE,
    **linux_fuse_shard(),
    "name": "Clippy (Rust linter)",
    "stage": Stage.test.value,
    "before_script": [
      "ulimit -c unlimited",
      "ulimit -n 8192",
    ],
    "script": ["./build-support/bin/ci.py --clippy"],
    "env": ["CACHE_NAME=clippy"],
  }


def cargo_audit() -> Dict:
  return {
    **linux_fuse_shard(),
    "name": "Cargo audit",
    "stage": Stage.test_cron.value,
    "script": ["./build-support/bin/ci.py --cargo-audit"],
    "env": ["CACHE_NAME=cargo_audit"],
  }

# -------------------------------------------------------------------------
# Unit tests
# -------------------------------------------------------------------------

def unit_tests(python_version: PythonVersion) -> Dict:
  shard = {
    **linux_shard(python_version=python_version, install_travis_wait=True),
    "name": f"Unit tests (Python {python_version.decimal})",
    "script": [
      "travis-wait-enhanced --timeout 65m --interval 9m -- ./build-support/bin/ci.py --unit-tests --plugin-tests "
      f"--remote-execution-enabled --python-version {python_version.decimal}"
    ],
  }
  shard["env"] = shard.get("env", []) + [f"CACHE_NAME=unit_tests.py{python_version.number}"]
  return shard

# ----------------------------------------------------------------------
# Build wheels
# ----------------------------------------------------------------------

def _build_wheels_command() -> List[str]:
  return [
    "./build-support/bin/check_pants_pex_abi.py abi3 cp36m",
    "RUN_PANTS_FROM_PEX=1 ./build-support/bin/release.sh -n",
  ]


def _build_wheels_env(*, platform: Platform) -> List[str]:
  return [
    "PREPARE_DEPLOY=1",
    f"CACHE_NAME=wheels.{platform}.py36",
  ]


def build_wheels_linux() -> Dict:
  command = " && ".join(_build_wheels_command())
  shard = {
    **linux_shard(python_version=PythonVersion.py36, use_docker=True),
    "name": "Build Linux wheels (Python 3.6)",
    "script": [
      docker_build_travis_ci_image(python_version=PythonVersion.py36),
      docker_run_travis_ci_image(command)
    ]
  }
  shard["env"] = shard.get("env", []) + (_build_wheels_env(platform=Platform.linux))
  return shard


def build_wheels_osx() -> Dict:
  shard = {
    **osx_shard(python_version=PythonVersion.py36, osx_image="xcode8"),
    "name": "Build OSX wheels (Python 3.6)",
    "script": _build_wheels_command(),
  }
  shard["env"] = shard.get("env", []) + _build_wheels_env(platform=Platform.osx) + [
    # We ensure selection of the pyenv interpreter by PY aware scripts and pants.pex with these
    # env vars.
    'PY=${PYENV_ROOT}/versions/${PYENV_PY36_VERSION}/bin/python',
    """PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS="['CPython==${PYENV_PY36_VERSION}']\""""
  ]
  return shard

# -------------------------------------------------------------------------
# Integration tests
# -------------------------------------------------------------------------

def integration_tests_v1(python_version: PythonVersion, *, use_pantsd: bool = False) -> List[Dict]:
  num_integration_shards = 7

  def make_shard(*, shard_num: int) -> Dict:
    shard = {
      **linux_shard(python_version=python_version),
      "name": f"Integration tests {'with Pantsd' if use_pantsd else ''} - V1 - shard {shard_num} (Python {python_version.decimal})",
      "script": [
        (
          "./build-support/bin/ci.py --integration-tests-v1 --integration-shard "
          f"{shard_num}/{num_integration_shards} --python-version {python_version.decimal}"
        ),
      ]
    }
    shard["env"] = shard.get("env", []) + [
      f"CACHE_NAME=integration.v1.shard_{shard_num}.py{python_version.number}{'.pantsd' if use_pantsd else ''}"
    ]
    if use_pantsd:
      shard["stage"] = Stage.test_cron.value
      shard["env"].append('USE_PANTSD_FOR_INTEGRATION_TESTS="true"')
    return shard
  return [make_shard(shard_num=i) for i in range(num_integration_shards)]


def integration_tests_v2(python_version: PythonVersion) -> Dict:
  shard = {
    **linux_shard(python_version=python_version, install_travis_wait=True),
    "name": f"Integration tests - V2 (Python {python_version.decimal})",
    "script": [
      (
        "travis-wait-enhanced --timeout 65m --interval 9m -- ./build-support/bin/ci.py --integration-tests-v2 "
        f"--remote-execution-enabled --python-version {python_version.decimal}"
      ),
    ]
  }
  shard["env"] = shard.get("env", []) + [
    f"CACHE_NAME=integration.v2.py{python_version.number}"
  ]
  return shard

# -------------------------------------------------------------------------
# Rust tests
# -------------------------------------------------------------------------

_RUST_TESTS_BASE = {
  **CACHE_NATIVE_ENGINE,
  "stage": Stage.test.value,
  "before_script": ["ulimit -c unlimited", "ulimit -n 8192"],
  "script": ["./build-support/bin/ci.py --rust-tests"],
}


def rust_tests_linux() -> Dict:
  return {
    **_RUST_TESTS_BASE,
    **linux_fuse_shard(),
    "name": "Rust tests - Linux",
    "env": ["CACHE_NAME=rust_tests.linux"]
  }


def rust_tests_osx() -> Dict:
  return {
    **_RUST_TESTS_BASE,
    "name": "Rust tests - OSX",
    "os": "osx",
    # We need to use xcode8.3 because newer versions of OSX won't let new kexts be installed
    # without travis taking some action, and we need the osxfuse kext.
    # See https://github.com/travis-ci/travis-ci/issues/10017
    "osx_image": "xcode8.3",
    "before_install": [
      './build-support/bin/install_python_for_ci.sh "${PYENV_PY36_VERSION}"',
      # We don't use the standard travis "addons" section here because it will either silently
      # fail (on older images) or cause a multi-minute `brew update` (on newer images), neither of
      # which we want. This doesn't happen if we just manually run `brew cask install`.
      #
      # Also, you will notice in the travis log that it says that OSX needs to be rebooted before
      # this install will work. This is a lie.
      "brew cask install osxfuse",
      # We don't need to install openssl because it already happens to be installed on this image.
      # This is good, because `brew install openssl` would trigger the same issues as noted on why
      # we don't use the `addons` section.
    ],
    "env": _osx_env_with_pyenv(python_version=PythonVersion.py36) + [
      "CACHE_NAME=rust_tests.osx"
    ]
  }

# -------------------------------------------------------------------------
# OSX platform tests
# -------------------------------------------------------------------------

def osx_platform_tests(python_version: PythonVersion) -> Dict:
  shard = {
    **osx_shard(python_version=python_version),
    "name": f"OSX platform-specific tests (Python {python_version.decimal})",
    "script": [
      f"./build-support/bin/ci.py --platform-specific-tests --python-version {python_version.decimal}"
    ],
  }
  shard["env"] = shard.get("env", []) + [f"CACHE_NAME=osx_platform_tests.py{python_version.number}"]
  return shard

# -------------------------------------------------------------------------
# OSX sanity checks
# -------------------------------------------------------------------------

def _osx_sanity_check(
  python_version: PythonVersion, *, os_version_number: int, osx_image: str
) -> Dict:
  shard = {
    **osx_shard(python_version=python_version, osx_image=osx_image),
    "name": f"OSX 10.{os_version_number} sanity check (Python {python_version.decimal})",
    "script": [
      f"MODE=debug ./build-support/bin/ci.py --sanity-checks --python-version {python_version.decimal}"
    ],
  }
  shard["env"] = shard.get("env", []) + [f"CACHE_NAME=osx_sanity.10_{os_version_number}.py{python_version.number}"]
  return shard


def osx_10_12_sanity_check(python_version: PythonVersion) -> Dict:
  return _osx_sanity_check(python_version, os_version_number=12, osx_image="xcode9.2")


def osx_10_13_sanity_check(python_version: PythonVersion) -> Dict:
  return _osx_sanity_check(python_version, os_version_number=13, osx_image="xcode10.1")

# -------------------------------------------------------------------------
# JVM tests
# -------------------------------------------------------------------------

def jvm_tests(python_version: PythonVersion) -> Dict:
  shard = {
    **linux_shard(python_version=python_version),
    # NB: linux_fuse comes after linux_shard to ensure that linux_fuse's before_install
    # entry is used.
    **linux_fuse_shard(),
    "name": f"JVM tests (Python {python_version.decimal})",
    "script": [f"./build-support/bin/ci.py --jvm-tests --python-version {python_version.decimal}"]
  }
  shard["env"] = shard.get("env", []) + [f"CACHE_NAME=jvm_tests.py{python_version.number}"]
  return shard

# -------------------------------------------------------------------------
# Deploy
# -------------------------------------------------------------------------

_DEPLOY_REPO = "pantsbuild/pants"

DEPLOY_SETTINGS = {
  "provider": "script",
  "script": "./build-support/bin/deploy_to_s3.py",
  # Otherwise travis will stash dist/deploy and the deploy will fail.
  "skip_cleanup": True,
  "on": {
    "condition": "$PREPARE_DEPLOY = 1",
    # NB: We mainly want deploys for `master` commits; but we also need new binaries for stable
    # release branches; eg `1.3.x`
    "all_branches": True,
    "repo": _DEPLOY_REPO,
  }
}


def _deploy_base() -> Dict:
  return {
    "os": "linux",
    "dist": "trusty",
    "language": "python",
    "python": ["3.6"],
    "before_install": [
      # TODO(John Sirois): Get rid of this in favor of explicitly adding pyenv versions to the PATH:
      #   https://github.com/pantsbuild/pants/issues/7601
      "pyenv global 3.6.3",
    ],
    "script": ["./build-support/bin/release.sh -p"],
    "env": ["RUN_PANTS_FROM_PEX=1"]
  }


def deploy_stable() -> Dict:
  shard = {
    **_deploy_base(),
    "name": "Deploy stable pants.pex (Python 3.6)",
    "stage": Stage.build_stable.value,
    "deploy": {
      # See https://docs.travis-ci.com/user/deployment/releases/
      "provider": "releases",
      # The pantsbuild-ci-bot OAuth token, see the pantsbuild vault for details.
      "api_key": {
        "secure": "u0aCsiuVGOg28YxG0sQUovuUm29kKwQfFgHbNz2TT5L+cGoHxGl4aoVOCtuwWYEtbNGmYc8/3WRS3C/jOiqQj6JEgHUzWOsnfKUObEqNhisAmXbzBbKc0wPQTL8WNK+DKFh32sD3yPYcw+a5PTLO56+o7rqlI25LK7A17WesHC4="
      },
      "file_glob": True,
      "file": "dist/deploy/pex/*",
      "skip_cleanup": True,
      "on": {
        # We only release a pex for Pants releases, which are tagged.
        "tags": True,
        "repo": _DEPLOY_REPO
      }
    }
  }
  shard["env"] = shard.get("env", []) + ["PANTS_PEX_RELEASE=stable", "CACHE_NAME=deploy.stable"]
  return shard


def deploy_unstable() -> Dict:
  shard = {
    **_deploy_base(),
    "name": "Deploy unstable pants.pex (Python 3.6)",
    "stage": Stage.build_unstable.value,
  }
  shard["script"] = shard.get("script", []) + [
    "mkdir -p dist/deploy/pex/",
    "mv dist/pants*.pex dist/deploy/pex/",
  ]
  shard["env"] = shard.get("env", []) + ["PREPARE_DEPLOY=1", "CACHE_NAME=deploy.unstable"]
  return shard

# ----------------------------------------------------------------------
# Main file
# ----------------------------------------------------------------------

# PyYAML will try by default to use anchors to deduplicate certain code. The alias
# names are cryptic, though, like `&id002`, so we turn this feature off.
class NoAliasDumper(yaml.SafeDumper):
  def ignore_aliases(self, data):
    return True


def main() -> None:
  generated_yaml = yaml.dump({
    # Conditions are documented here: https://docs.travis-ci.com/user/conditions-v1
    "conditions": "v1",
    "env": {"global": GLOBAL_ENV_VARS},
    "stages": Stage.all_entries(),
    "deploy": DEPLOY_SETTINGS,
    "matrix": {"include": [
      *[bootstrap_linux(v) for v in PythonVersion],
      *[bootstrap_osx(v) for v in PythonVersion],
      {**bootstrap_linux(PythonVersion.py36), "stage": Stage.bootstrap_cron.value},
      {**bootstrap_osx(PythonVersion.py36), "stage": Stage.bootstrap_cron.value},
      # NB: We move both the unit test and V2 integration test shards up here to ensure that
      # they are shards #5 and #6. Per the token generator design
      # https://docs.google.com/document/d/1gL3D1f-AzL_LzRxWLskCpVQ2ZlB_26GTETgXkXsrpDY/edit#heading=h.akhkfdtqfpw,
      # the RBE token server will only give tokens to job numbers #5 and #6, so we must do this
      # for the cron jobs to work with remoting.
      unit_tests(PythonVersion.py37),
      integration_tests_v2(PythonVersion.py37),
      *[lint(v) for v in PythonVersion],
      clippy(),
      cargo_audit(),
      unit_tests(PythonVersion.py36),
      integration_tests_v2(PythonVersion.py36),
      build_wheels_linux(),
      build_wheels_osx(),
      *integration_tests_v1(PythonVersion.py36),
      *integration_tests_v1(PythonVersion.py36, use_pantsd=True),
      *integration_tests_v1(PythonVersion.py37),
      rust_tests_linux(),
      rust_tests_osx(),
      *[osx_platform_tests(v) for v in PythonVersion],
      *[osx_10_12_sanity_check(v) for v in PythonVersion],
      *[osx_10_13_sanity_check(v) for v in PythonVersion],
      *[jvm_tests(v) for v in PythonVersion],
      deploy_stable(),
      deploy_unstable(),
    ]},
  }, Dumper=NoAliasDumper)
  print(f"{HEADER}\n\n{generated_yaml}")


if __name__ == '__main__':
  main()
