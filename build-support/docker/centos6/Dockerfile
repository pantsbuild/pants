# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Use centos6 for compatibility with glibc 2.12.
FROM centos:6

# Ensure Pants runs under the 2.7.13 interpreter.
ENV PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS="['CPython==2.7.13']"

# TODO: Not https? Now we're really doing some science!
RUN curl -o /etc/yum.repos.d/slc6-devtoolset.repo http://linuxsoft.cern.ch/cern/devtoolset/slc6-devtoolset.repo
RUN rpm --import http://linuxsoft.cern.ch/cern/slc6X/x86_64/RPM-GPG-KEY-cern

# Install python 2.7.13, (more) modern gcc, and a JDK.
RUN yum -y update
RUN yum install -y centos-release-scl
RUN yum install -y \
  devtoolset-7-gcc \
  devtoolset-7-gcc-c++ \
  git \
  java-1.8.0-openjdk-devel \
  python27

# By default, execute in an environment with python27 enabled.
ENTRYPOINT ["/usr/bin/scl", "enable", "python27", "devtoolset-7",  "--"]
