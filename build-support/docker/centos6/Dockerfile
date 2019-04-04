# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Use centos6 for compatibility with glibc 2.12.
FROM centos:6

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
