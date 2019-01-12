# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Use our custom Centos6 image for binary compatibility with old linux distros.
FROM pantsbuild/centos6:latest

# -----------------------------------------------------------------------
# This section belongs in centos6, but is here temporarily because
# centos6's build must first be published to Docker.

RUN yum install sqlite-devel -y
RUN mkdir -p /python-3-docker-build/python-3.6.8-{source,install}
RUN curl -L -v https://www.python.org/ftp/python/3.6.8/Python-3.6.8.tgz \
    | tar -zxvC /python-3-docker-build/python-3.6.8-source
RUN /usr/bin/scl enable devtoolset-7 -- \
    bash -c 'pushd /python-3-docker-build/python-3.6.8-source/Python-3.6.8 \
         && ./configure --prefix=/python-3-docker-build/python-3.6.8-install \
                        --enable-optimizations \
         && make install'
ENV PATH "${PATH}:/python-3-docker-build/python-3.6.8-install/bin"

# -----------------------------------------------------------------------

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
