# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Use our custom Centos6 image for binary compatibility with old linux distros.
FROM pantsbuild/centos6:latest

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

# -----------------------------------------------------------------------
# This section belongs in centos6, but is here temporarily because
# centos6's build must first be published to Docker.

RUN yum -y update
RUN yum install -y centos-release-scl
RUN yum install -y wget

RUN cd /usr/src && \
  wget https://www.python.org/ftp/python/3.6.8/Python-3.6.8.tgz && \
  tar -xzf Python-3-6-8.tgz && \
  cd Python-3-6-8 && \
  ./configure --enable-optimizations && \
  make altinstall && \
  rm /usr/src/Python-3-6-8.tgz

# -----------------------------------------------------------------------

WORKDIR /travis/workdir
