# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# NB: this file duplicates travis_ci/Dockerfile, except it installs Python 2.7 with UCS2.
# We do not include this change directly in centos6/Dockerfile nor in travis_ci/Dockerfile
# because we only want access to this Python interpreter in the Build Wheels Linux UCS2 shard,
# so it is not helpful to other shards. Rather, it would make those shards more finicky to deal
# with by resulting in two Python 2.7 installs: system vs. pyenv.

# Use our custom Centos6 image for binary compatibility with old linux distros.
FROM pantsbuild/centos6:latest

# Note we use 2.7.15, rather than 2.7.13, as the centos6 image already comes with 2.7.13
# installed, which uses UCS4 instead of UCS2. This allows us to disambiguate which Python 2
# interpreter to use when `ci.sh` and `release.sh` set the interpreter constraints for
# Pants, and thus for the built ./pants.pex. We set $PY to the exact Python 2.7 version we want
# to ensure the PEX is bootstrapped with UCS 2.
ARG PYTHON_27_VERSION_UCS2=2.7.15
# TODO(7064): remove this yum install line once we update the base Centos6 image to include this dependency.
RUN yum install sqlite-devel -y
ENV PYENV_ROOT "${PYENV_ROOT:-/pyenv-docker-build}"
ENV PYENV_BIN ${PYENV_ROOT}/bin/pyenv
RUN if [[ ! -x "${PYENV_BIN}" ]]; then git clone https://github.com/pyenv/pyenv ${PYENV_ROOT}; fi
ENV PYTHON_CONFIGURE_OPTS --enable-unicode=ucs2
RUN /usr/bin/scl enable devtoolset-7 -- bash -c '${PYENV_BIN} install ${PYTHON_27_VERSION_UCS2}'
RUN /usr/bin/scl enable devtoolset-7 -- bash -c '${PYENV_BIN} global ${PYTHON_27_VERSION_UCS2}'
ENV PATH "${PYENV_ROOT}/versions/${PYTHON_27_VERSION_UCS2}:${PATH}"
ENV PY "${PYENV_ROOT}/versions/${PYTHON_27_VERSION_UCS2}/bin/python"
ENV PEX_PYTHON_PATH "${PYENV_ROOT}/versions/${PYTHON_27_VERSION_UCS2}/bin/python"

# Setup mount points for the travis ci user & workdir.
VOLUME /travis/home
VOLUME /travis/workdir

# Setup a non-root user to execute the build under (avoids problems with npm install).
ARG TRAVIS_USER=travis_ci
ARG TRAVIS_UID=1000
ARG TRAVIS_GROUP=root
ARG TRAVIS_GID=0

RUN groupadd --gid ${TRAVIS_GID} ${TRAVIS_GROUP} || true
RUN useradd -d /travis/home -g ${TRAVIS_GROUP} --uid ${TRAVIS_UID} ${TRAVIS_USER}
USER ${TRAVIS_USER}:${TRAVIS_GROUP}

# Our newly created user is unlikely to have a sane environment: set a locale at least.
ENV LC_ALL="en_US.UTF-8"

# This tells the ./pants runner script to avoid trying to clean the workspace when changing python
# versions. CI starts off without the .python-interpreter-constraints file, so it would otherwise run a
# clean-all without this env var.
ENV ONLY_USING_SINGLE_PYTHON_VERSION 'true'

WORKDIR /travis/workdir
