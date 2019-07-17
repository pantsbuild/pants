# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

FROM gcr.io/cloud-marketplace/google/rbe-ubuntu16-04@sha256:da0f21c71abce3bbb92c3a0c44c3737f007a82b60f8bd2930abc55fe64fc2729

RUN apt-get update
RUN apt-get install -y \
  build-essential \
  zlib1g-dev \
  libbz2-dev \
  libreadline-dev \
  libssl-dev \
  libsqlite3-dev \
  libffi-dev \
  python-openssl

# Even though the image already comes installed with Python 2.7, 3.5, and 3.6, we install our own
# via Pyenv because we need Python 3.7 and want consistency in how we install them.
ARG PYTHON_27_VERSION=2.7.15
ARG PYTHON_36_VERSION=3.6.8
ARG PYTHON_37_VERSION=3.7.3

ENV PYENV_ROOT /pyenv-docker-build
ENV PYENV_BIN "${PYENV_ROOT}/bin/pyenv"
RUN git clone https://github.com/pyenv/pyenv ${PYENV_ROOT}

RUN ${PYENV_BIN} install ${PYTHON_27_VERSION}
RUN ${PYENV_BIN} install ${PYTHON_36_VERSION}
RUN ${PYENV_BIN} install ${PYTHON_37_VERSION}

ENV PATH "${PYENV_ROOT}/versions/${PYTHON_27_VERSION}/bin:${PATH}"
ENV PATH "${PYENV_ROOT}/versions/${PYTHON_36_VERSION}/bin:${PATH}"
ENV PATH "${PYENV_ROOT}/versions/${PYTHON_37_VERSION}/bin:${PATH}"
