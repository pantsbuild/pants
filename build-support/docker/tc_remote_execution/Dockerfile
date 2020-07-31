# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

#   1. Install Docker.
#   2. $ docker build --tag pants-remote-execution build-support/docker/tc_remote_execution
#   3. $ docker push [needs docker hub tag]
#   4. Ask a toolchain developer on Slack in #infra channel to upload the new image.

FROM ubuntu:xenial-20200619

RUN apt-get update --fix-missing
RUN apt-get install -y \
  build-essential \
  curl \
  git \
  gcc-multilib \
  g++-multilib \
  libbz2-dev \
  liblzma-dev \
  libreadline-dev \
  libssl-dev \
  libsqlite3-dev \
  libffi-dev \
  openjdk-8-jdk-headless \
  openjdk-8-jre-headless \
  python-openssl \
  unzip \
  zip \
  zlib1g-dev

# Even though the image already comes installed with Python 2.7, 3.5, and 3.6, we install our own
# via Pyenv because we need Python 3.7 and want consistency in how we install them.
ARG PYTHON_27_VERSION=2.7.18
ARG PYTHON_36_VERSION=3.6.11
ARG PYTHON_37_VERSION=3.7.8
ARG PYTHON_38_VERSION=3.8.5

ENV PYENV_ROOT /pyenv-docker-build
ENV PYENV_BIN "${PYENV_ROOT}/bin/pyenv"
RUN git clone https://github.com/pyenv/pyenv ${PYENV_ROOT}

RUN ${PYENV_BIN} install ${PYTHON_27_VERSION}
RUN ${PYENV_BIN} install ${PYTHON_36_VERSION}
RUN ${PYENV_BIN} install ${PYTHON_37_VERSION}
RUN ${PYENV_BIN} install ${PYTHON_38_VERSION}

ENV PATH "${PYENV_ROOT}/versions/${PYTHON_27_VERSION}/bin:${PATH}"
ENV PATH "${PYENV_ROOT}/versions/${PYTHON_36_VERSION}/bin:${PATH}"
ENV PATH "${PYENV_ROOT}/versions/${PYTHON_37_VERSION}/bin:${PATH}"
ENV PATH "${PYENV_ROOT}/versions/${PYTHON_38_VERSION}/bin:${PATH}"
