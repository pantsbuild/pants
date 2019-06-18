# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

FROM centos:7

# Install a (more) modern gcc, a JDK, and dependencies for installing Python through Pyenv.
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

ENV PYENV_ROOT /pyenv-docker-build
ENV PYENV_BIN "${PYENV_ROOT}/bin/pyenv"
RUN git clone https://github.com/pyenv/pyenv ${PYENV_ROOT}

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
