# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Use centos6 for compatibility with glibc 2.12.
FROM centos:6

# Install a (more) modern gcc, a JDK, and dependencies for installing Python through Pyenv.
# Also install sqlite-devel because Python 3 errors on startup if not -- see
# https://stackoverflow.com/a/39907500/2518889.
RUN yum -y update
# TODO: figure out why this needs to be installed first for /usr/bin/scl to work!
RUN yum install -y centos-release-scl
RUN yum install -y \
        bzip2-devel \
        devtoolset-7-gcc{,-c++} \
        git \
        java-1.8.0-openjdk-devel \
        libffi-devel \
        openssl-devel \
        readline-devel \
        sqlite-devel \
        zlib-devel

ARG PYTHON_27_VERSION=2.7.13
ARG PYTHON_36_VERSION=3.6.8

ENV PYENV_ROOT /pyenv-docker-build
ENV PYENV_BIN "${PYENV_ROOT}/bin/pyenv"
RUN git clone https://github.com/pyenv/pyenv ${PYENV_ROOT}

# NB: We intentionally do not use `--enable-shared`, as it results in our shipped wheels for the PEX release using
# `libpython.X.Y.so.1`, which means that the PEX will not work for any consumer interpreters that were statically
# built, i.e. compiled without `--enable-shared`. See https://github.com/pantsbuild/pants/pull/7794.
RUN /usr/bin/scl enable devtoolset-7 -- ${PYENV_BIN} install ${PYTHON_27_VERSION}
RUN /usr/bin/scl enable devtoolset-7 -- ${PYENV_BIN} install ${PYTHON_36_VERSION}

ENV PATH "${PYENV_ROOT}/versions/${PYTHON_27_VERSION}/bin:${PATH}"
ENV PATH "${PYENV_ROOT}/versions/${PYTHON_36_VERSION}/bin:${PATH}"

# Expose the installed gcc to the invoking shell.
ENTRYPOINT ["/usr/bin/scl", "enable", "devtoolset-7",  "--"]
