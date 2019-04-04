# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Use our custom Centos6 image for binary compatibility with old linux distros.
ARG BASE_IMAGE=pantsbuild/centos6:latest
FROM ${BASE_IMAGE}

# TODO(7064) These changes belong in centos6/Dockerfile, because we always want that image to
# have Py3 available and also avoid the cost of rebuilding Python 3 every time in CI. However,
# this requires publishing an updated image to Docker hub, so we copy the code here until then.

### BEGIN CENTOS6 DOCKERFILE CHANGES
# Install a (more) modern gcc, a JDK, and dependencies for installing Python through Pyenv.
# Also install sqlite-devel because python 3 errors on startup if not -- see
# https://stackoverflow.com/a/39907500/2518889.
RUN yum -y update
# TODO: figure out why this needs to be installed first for /usr/bin/scl to work!
RUN yum install -y centos-release-scl
RUN yum install -y \
        bzip2{,-devel} \
        devtoolset-7-gcc{,-c++} \
        git \
        java-1.8.0-openjdk-devel \
        libffi{,-devel} \
        openssl-devel \
        readline{,-devel} \
        sqlite-devel \
        zlib{,-devel}

ARG PYTHON_27_VERSION=2.7.13
ARG PYTHON_36_VERSION=3.6.8
# NB: PYENV_ROOT must be set for `pyenv install` to be available. This failure mode is not mentioned
# in https://github.com/pyenv/pyenv#basic-github-checkout.
ENV PYENV_ROOT /pyenv-docker-build
RUN mkdir ${PYENV_ROOT}
RUN git clone https://github.com/pyenv/pyenv ${PYENV_ROOT}
ENV PYENV_BIN ${PYENV_ROOT}/bin/pyenv

# Install python 2.7 and 3.6, and set python 3.6 as the default interpreter.
# Build the python shared library, in addition to openssl, as we use it to build the engine.
ENV PYTHON_CONFIGURE_OPTS="--enable-shared --with-openssl=${OPENSSL_DIR}"
RUN /usr/bin/scl enable devtoolset-7 -- ${PYENV_BIN} install ${PYTHON_27_VERSION}
RUN /usr/bin/scl enable devtoolset-7 -- ${PYENV_BIN} install ${PYTHON_36_VERSION}
RUN ${PYENV_BIN} global ${PYTHON_27_VERSION} ${PYTHON_36_VERSION}
ENV PATH "${PYENV_ROOT}/shims:${PATH}"

# Expose the installed gcc to the invoking shell.
ENTRYPOINT ["/usr/bin/scl", "enable", "devtoolset-7",  "--"]

### END CENTOS6 DOCKERFILE CHANGES

ARG TRAVIS_HOME_DIR_PATH=/travis/home
ARG TRAVIS_WORK_DIR_PATH=/travis/workdir

RUN mkdir -p ${TRAVIS_HOME_DIR_PATH}
RUN mkdir -p ${TRAVIS_WORK_DIR_PATH}

# Setup a non-root user to execute the build under (avoids problems with npm install).
ARG TRAVIS_USER=travis_ci
ARG TRAVIS_UID=1000
ARG TRAVIS_GROUP=root
ARG TRAVIS_GID=0

RUN groupadd --gid ${TRAVIS_GID} ${TRAVIS_GROUP} || true
RUN useradd -d ${TRAVIS_HOME_DIR_PATH} -g ${TRAVIS_GROUP} --uid ${TRAVIS_UID} ${TRAVIS_USER}

RUN chown -R ${TRAVIS_USER} ${TRAVIS_HOME_DIR_PATH}
RUN chown -R ${TRAVIS_USER} ${TRAVIS_WORK_DIR_PATH}

USER ${TRAVIS_USER}:${TRAVIS_GROUP}

# Our newly created user is unlikely to have a sane environment: set a locale at least.
ENV LC_ALL="en_US.UTF-8"

# This tells the ./pants runner script to avoid trying to clean the workspace when changing python
# versions. CI starts off without the .python-interpreter-constraints file, so it would otherwise run a
# clean-all without this env var.
ENV ONLY_USING_SINGLE_PYTHON_VERSION 'true'

# Expose the installed gcc to the invoking shell.
ENTRYPOINT ["/usr/bin/scl", "enable", "devtoolset-7",  "--"]

WORKDIR ${TRAVIS_WORK_DIR_PATH}
