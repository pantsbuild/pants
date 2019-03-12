# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Use centos6 for compatibility with glibc 2.12.
FROM centos:6

# Install a (more) modern gcc, and a JDK.
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

# Install custom OpenSSL as Python 3.7 requires at least OpenSSL 1.0.2:
# https://docs.python.org/3/whatsnew/3.7.html#platform-support-removals.
# Centos6's system OpenSSL is too outdated for this. Note solution is adapted
# from PEX's Tox setup: https://github.com/pantsbuild/pex/blob/1b9e509ae36303d222445611420879bd4edcb1b1/.travis.yml#L46-L86.
ARG OPENSSL_VERSION=1.0.2p
ENV OPENSSL_DIR=/openssl-docker-build
ENV LD_LIBRARY_PATH="${OPENSSL_DIR}/lib"
# `scl enable devtoolset-7` puts the gcc we just installed on the PATH for that command.
RUN /usr/bin/scl enable devtoolset-7 -- bash -c '\
    curl https://www.openssl.org/source/openssl-${OPENSSL_VERSION}.tar.gz | tar -xz \
    && cd openssl-${OPENSSL_VERSION} \
    && ./config shared --prefix="${OPENSSL_DIR}" \
    && make --quiet \
    && make install --quiet \
    && touch "${OPENSSL_DIR}/installed-${OPENSSL_VERSION}"'

# Install the desired versions of python 2.7 and 3.6.
ARG PYTHON_27_VERSION=2.7.13
ARG PYTHON_36_VERSION=3.6.8
# NB: PYENV_ROOT must be set in the environment for `pyenv install` to work, otherwise it will
# mysteriously fail to find the `install` command (although other commands are available).
ENV PYENV_ROOT /pyenv-docker-build
RUN mkdir ${PYENV_ROOT}
RUN git clone https://github.com/pyenv/pyenv ${PYENV_ROOT}

# Install python 2.7 and 3.6, and set python 3.6 as the default interpreter.
# Build the python shared library, in addition to openssl, as we use it to build the engine.
ENV PYTHON_CONFIGURE_OPTS="--enable-shared --with-openssl=${OPENSSL_DIR}"
RUN /usr/bin/scl enable devtoolset-7 -- ${PYENV_ROOT}/bin/pyenv install ${PYTHON_27_VERSION}
RUN /usr/bin/scl enable devtoolset-7 -- ${PYENV_ROOT}/bin/pyenv install ${PYTHON_36_VERSION}
RUN ${PYENV_ROOT}/bin/pyenv global ${PYTHON_27_VERSION} ${PYTHON_36_VERSION}
ENV PATH "${PYENV_ROOT}/shims:${PATH}"

# Expose the installed gcc to the invoking shell.
ENTRYPOINT ["/usr/bin/scl", "enable", "devtoolset-7",  "--"]
