# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# TODO(7064): this file duplicates travis_ci/Dockerfile, except it installs Python 3.6.
# We split it out into a separate file to avoid the cost of installing Python 3.6 for Py2 only
# shards. Ideally this file would not exist though, as these changes belong in the base
# image Centos6! Once those changes are published to Dockerhub, this file should be deleted
# and the shards should go back to using `travis_ci`.

# Use our custom Centos6 image for binary compatibility with old linux distros.
FROM pantsbuild/centos6:latest

# ----------------------------------------------------------
# TODO(7064) Add all the below changes to Centos6 image.

RUN yum install sqlite-devel -y
ARG PYTHON_36_VERSION=3.6.8
ENV PYENV_ROOT /pyenv-docker-build
RUN mkdir ${PYENV_ROOT}
RUN git clone https://github.com/pyenv/pyenv ${PYENV_ROOT}
RUN /usr/bin/scl enable devtoolset-7 -- bash -c '\
    ${PYENV_ROOT}/bin/pyenv install ${PYTHON_36_VERSION} \
    && ${PYENV_ROOT}/bin/pyenv global ${PYTHON_36_VERSION}'
ENV PATH "${PYENV_ROOT}/shims:${PATH}"

# End TODO(7064)
# ----------------------------------------------------------

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

# TODO(#7152): this tells the ./pants runner script to avoid trying to clean the workspace when
# changing python versions. Remove all instances of this after the python 3 migration!
ENV ONLY_USING_SINGLE_PYTHON_VERSION 'true'

WORKDIR /travis/workdir
