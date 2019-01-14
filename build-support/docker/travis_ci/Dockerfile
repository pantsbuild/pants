# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Use our custom Centos6 image for binary compatibility with old linux distros.
FROM pantsbuild/centos6:latest

# TODO(7064) These changes belong in centos6/Dockerfile, because we always want that image to
# have Py3 available and also avoid the cost of rebuilding Python 3 every time in CI. However,
# this requires publishing an updated image to Docker hub, so we copy the code here until then.
ARG PYTHON_3_VERSION=3.6.8
RUN yum install sqlite-devel -y
ENV PYENV_ROOT /pyenv-docker-build
RUN mkdir ${PYENV_ROOT}
RUN git clone https://github.com/pyenv/pyenv ${PYENV_ROOT}
RUN /usr/bin/scl enable devtoolset-7 -- bash -c '\
    ${PYENV_ROOT}/bin/pyenv install ${PYTHON_3_VERSION} \
    && ${PYENV_ROOT}/bin/pyenv global ${PYTHON_3_VERSION}'

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
