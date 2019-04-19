# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Use our custom Centos6 image for binary compatibility with old linux distros.
ARG BASE_IMAGE=pantsbuild/centos6:latest
FROM ${BASE_IMAGE}

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

# Expose the installed gcc to the invoking shell.
ENTRYPOINT ["/usr/bin/scl", "enable", "devtoolset-7",  "--"]

WORKDIR ${TRAVIS_WORK_DIR_PATH}
