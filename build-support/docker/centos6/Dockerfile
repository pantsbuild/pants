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

ARG PYTHON_3_SOURCE_URL=https://www.python.org/ftp/python/3.6.8/Python-3.6.8.tgz
RUN mkdir -p /python-3-docker-build/python-3-{source,install}
# The --strip=1 argument above removes the initial path component -- see tar(1).
RUN curl -L -v ${PYTHON_3_SOURCE_URL} \
    | tar -zxv -C /python-3-docker-build/python-3-source --strip=1
RUN /usr/bin/scl enable devtoolset-7 -- bash -c '\
    pushd /python-3-docker-build/python-3-source/ \
         && ./configure --prefix=/python-3-docker-build/python-3-install \
                        --enable-optimizations \
         && make install'
# Add the built python to the end of the PATH.
ENV PATH "${PATH}:/python-3-docker-build/python-3-install/bin"

# By default, execute in an environment with python27 enabled.
ENTRYPOINT ["/usr/bin/scl", "enable", "python27", "devtoolset-7",  "--"]
