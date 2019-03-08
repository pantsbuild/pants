# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This file duplicates travis_ci/Dockerfile, except it installs Python 2.7 instead of Python 3.6
# and adds the env var PYTHON_CONFIGURE_OPTS to install it with UCS2.

# Use our custom Centos6 image for binary compatibility with old linux distros.
FROM pantsbuild/centos6:latest

# Note we use 2.7.15, rather than 2.7.13, as the centos6 image already comes with 2.7.13
# installed, which uses UCS4 instead of UCS2. This allows us to disambiguate which Python 2
# interpreter to use when `ci.sh` and `release.sh` set the interpreter constraints for
# Pants, and thus for the built ./pants.pex. We set $PY to the exact Python 2.7 version we want
# to ensure the PEX is bootstrapped with UCS 2.
ARG PYTHON_2_VERSION=2.7.15
RUN yum install sqlite-devel unzip -y
ENV PYENV_ROOT /pyenv-docker-build
RUN mkdir ${PYENV_ROOT}
RUN git clone https://github.com/pyenv/pyenv ${PYENV_ROOT}
ENV PYTHON_CONFIGURE_OPTS --enable-unicode=ucs2
RUN /usr/bin/scl enable devtoolset-7 -- bash -c '\
    ${PYENV_ROOT}/bin/pyenv install ${PYTHON_2_VERSION} \
    && ${PYENV_ROOT}/bin/pyenv global ${PYTHON_2_VERSION}'
ENV PATH "${PYENV_ROOT}/shims:${PATH}"
ENV PY "${PYENV_ROOT}/shims/python2.7"
ENV PEX_PYTHON_PATH "${PYENV_ROOT}/shims/python2.7"

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

WORKDIR /travis/workdir
