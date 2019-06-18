# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Use our custom Centos6 image for binary compatibility with old linux distros.
#ARG BASE_IMAGE=pantsbuild/centos6:latest
#FROM ${BASE_IMAGE}

# -----------------------------------------------------------------
# Start inline
# -----------------------------------------------------------------

FROM centos:7

# Install a (more) modern gcc, a JDK, and dependencies for installing Python through Pyenv.
# Also install sqlite-devel because Python 3 errors on startup if not -- see
# https://stackoverflow.com/a/39907500/2518889.
RUN yum -y update
RUN yum install -y centos-release-scl
RUN yum install -y \
        make \
        devtoolset-7-gcc{,-c++} \
        git \
        java-1.8.0-openjdk-devel \
        bzip2-devel \
        libffi-devel \
        openssl-devel \
        readline-devel \
        sqlite-devel \
        zlib-devel

ARG PYTHON_27_VERSION=2.7.13
ARG PYTHON_36_VERSION=3.6.8
ARG PYTHON_37_VERSION=3.7.3
# NB: PYENV_ROOT must be set for `pyenv install` to be available. This failure mode is not mentioned
# in https://github.com/pyenv/pyenv#basic-github-checkout.
ENV PYENV_ROOT /pyenv-docker-build
ENV PYENV_BIN "${PYENV_ROOT}/bin/pyenv"
RUN git clone https://github.com/pyenv/pyenv ${PYENV_ROOT}

# Install Python 2.7, 3.6, and 3.7.
# NB: We intentionally do not use `--enable-shared`, as it results in our shipped wheels for the PEX release using
# `libpython.X.Y.so.1`, which means that the PEX will not work for any consumer interpreters that were statically
# built, i.e. compiled without `--enable-shared`. See https://github.com/pantsbuild/pants/pull/7794.
RUN /usr/bin/scl enable devtoolset-7 -- ${PYENV_BIN} install ${PYTHON_27_VERSION}
RUN /usr/bin/scl enable devtoolset-7 -- ${PYENV_BIN} install ${PYTHON_36_VERSION}
RUN /usr/bin/scl enable devtoolset-7 -- ${PYENV_BIN} install ${PYTHON_37_VERSION}
RUN ${PYENV_BIN} global ${PYTHON_27_VERSION} ${PYTHON_36_VERSION} ${PYTHON_37_VERSION}
ENV PATH "${PYENV_ROOT}/shims:${PATH}"

# Expose the installed gcc to the invoking shell.
ENTRYPOINT ["/usr/bin/scl", "enable", "devtoolset-7",  "--"]

# -----------------------------------------------------------
# End inline
# -----------------------------------------------------------

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

WORKDIR ${TRAVIS_WORK_DIR_PATH}

# Execute any args passed to `docker run` in the context of the devtoolset-7 software collection
# used in the base image to install requirements.
ENTRYPOINT ["/usr/bin/scl", "enable" , "devtoolset-7", "--"]
