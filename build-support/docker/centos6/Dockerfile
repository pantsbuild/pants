# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Use centos6 for compatibility with glibc 2.12.
FROM centos:6

# Install python 2.7.13, (more) modern gcc, and a JDK.
RUN yum -y update
# TODO: figure out why this needs to be installed first for /usr/bin/scl to work!
RUN yum install -y centos-release-scl
RUN yum install -y devtoolset-7-gcc{,-c++} \
  git \
  java-1.8.0-openjdk-devel \
  python27 \
  libffi{,-devel} \
  openssl-devel \
  sqlite-devel

# Install the desired version of python 3.
ARG PYTHON_3_VERSION=3.6.8
# NB: PYENV_ROOT must be set in the environment for `pyenv install` to work, otherwise it will
# mysteriously fail to find the `install` command.
ENV PYENV_ROOT /pyenv-py3-docker-build
RUN mkdir ${PYENV_ROOT}
RUN git clone https://github.com/pyenv/pyenv ${PYENV_ROOT}
RUN /usr/bin/scl enable devtoolset-7 -- bash -c '\
    ${PYENV_ROOT}/bin/pyenv install --keep --skip-existing ${PYTHON_3_VERSION} \
    && ${PYENV_ROOT}/bin/pyenv global ${PYTHON_3_VERSION}'
ENV PATH "${PYENV_ROOT}/shims:${PATH}"

# By default, execute in an environment with python27 enabled.
ENTRYPOINT ["/usr/bin/scl", "enable", "python27", "devtoolset-7",  "--"]
