# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Use centos6 for compatibility with glibc 2.12.
FROM centos:6

# Install python 2.7.13, (more) modern gcc, and a JDK.
RUN yum -y update
RUN yum install -y centos-release-scl
RUN yum install -y \
  devtoolset-7-gcc \
  devtoolset-7-gcc-c++ \
  git \
  java-1.8.0-openjdk-devel \
  python27 \
  libffi \
  libffi-devel \
  openssl-devel

# By default, execute in an environment with python27 enabled.
ENTRYPOINT ["/usr/bin/scl", "enable", "python27", "devtoolset-7",  "--"]
