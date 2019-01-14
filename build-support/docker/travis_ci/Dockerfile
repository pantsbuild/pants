# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Use our custom Centos6 image for binary compatibility with old linux distros.
FROM pantsbuild/centos6:latest

# TODO(7064) These changes belong in centos6/Dockerfile, because we always want that image to
# have Py3 available and also avoid the cost of rebuilding Python 3 every time in CI. However,
# this requires publishing an updated image to Docker hub, so we copy the code here until then.
# Install the desired versions of python 2 and 3.
ARG PYTHON_2_VERSION=2.7.13
ARG PYTHON_3_VERSION=3.6.8
# NB: PYENV_ROOT must be set in the environment for `pyenv install` to work, otherwise it will
# mysteriously fail to find the `install` command.
ENV PYENV_ROOT /pyenv-docker-build
RUN mkdir ${PYENV_ROOT}
RUN git clone https://github.com/pyenv/pyenv ${PYENV_ROOT}
# Install python 2 and 3, and set python 2 as the default interpreter.
RUN /usr/bin/scl enable devtoolset-7 -- bash -c '\
    ${PYENV_ROOT}/bin/pyenv install --keep --skip-existing ${PYTHON_2_VERSION} \
    && ${PYENV_ROOT}/bin/pyenv install --keep --skip-existing ${PYTHON_3_VERSION} \
    && ${PYENV_ROOT}/bin/pyenv global ${PYTHON_2_VERSION}'
ENV PATH "${PYENV_ROOT}/shims:${PATH}"

# By default, execute in an environment with python27 enabled.
ENTRYPOINT ["/usr/bin/scl", "enable", "devtoolset-7",  "--"]

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
