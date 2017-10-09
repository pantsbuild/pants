# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Use the standard python-2.7 docker Debian Wheezy image for binary compatibility with old linux
# distros.
FROM python:2.7.13-wheezy

# The native engine has a dependency on gRPC which builds with cmake.
RUN bash -c "pushd /tmp && \
 curl -O https://cmake.org/files/v3.8/cmake-3.8.0.tar.gz && \
 tar xzf cmake-3.8.0.tar.gz && cd cmake-3.8.0 && \
 ./configure && make && make install && \
 popd && \
 rm -rf /tmp/cmake-3.8.0 /tmp/cmake-3.8.0.tar.gz"

# The native engine has a dependency on gRPC which requires go to build.
RUN bash -c "tar -C /usr/local -xzf <(curl https://binaries.pantsbuild.org/bin/go/linux/x86_64/1.7.6/go.tar.gz)"

ENV PATH="${PATH}:/usr/local/go/bin"

# Ensure Pants runs under the 2.7.13 interpreter.
ENV PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS="['CPython==2.7.13']"

# Install various things Pants requires.
RUN echo "deb http://ppa.launchpad.net/webupd8team/java/ubuntu trusty main" > \
      /etc/apt/sources.list.d/java-8-debian.list && \
    echo "deb-src http://ppa.launchpad.net/webupd8team/java/ubuntu trusty main" >> \
      /etc/apt/sources.list.d/java-8-debian.list && \
    apt-key adv --keyserver keyserver.ubuntu.com --recv-keys EEA14886 && \
    echo debconf shared/accepted-oracle-license-v1-1 select true | debconf-set-selections && \
    echo debconf shared/accepted-oracle-license-v1-1 seen true | debconf-set-selections && \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
      cmake \
      oracle-java8-installer

# Setup mount points for the travis ci user & workdir.
VOLUME /travis/workdir

# Setup a non-root user to execute the build under (avoids problems with npm install).
ARG TRAVIS_USER=travis_ci
ARG TRAVIS_UID=1000
ARG TRAVIS_GROUP=root
ARG TRAVIS_GID=0

RUN mkdir -p /travis/home

RUN groupadd --gid ${TRAVIS_GID} ${TRAVIS_GROUP}
RUN useradd -d /travis/home -g ${TRAVIS_GROUP} --uid ${TRAVIS_UID} ${TRAVIS_USER}
RUN chown ${TRAVIS_USER}:${TRAVIS_GROUP} /travis/home
USER ${TRAVIS_USER}:${TRAVIS_GROUP}

WORKDIR /travis/workdir
