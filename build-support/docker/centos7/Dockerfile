# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

FROM centos:7

# Install a (more) modern gcc, a JDK, and dependencies for installing Python through Pyenv.
RUN yum -y update
RUN yum install -y centos-release-scl
RUN yum install -y \
        make \
        devtoolset-7-gcc{,-c++} \
        git \
        java-1.8.0-openjdk-devel \
        bzip2-devel \
        libffi-devel \
        openssl-devel \
        readline-devel \
        sqlite-devel \
        unzip \
        zlib-devel

ARG PYTHON_27_VERSION=2.7.18
ARG PYTHON_36_VERSION=3.6.10
ARG PYTHON_37_VERSION=3.7.7
ARG PYTHON_38_VERSION=3.8.2

ENV PYENV_ROOT /pyenv-docker-build
ENV PYENV_BIN "${PYENV_ROOT}/bin/pyenv"
RUN git clone https://github.com/pyenv/pyenv ${PYENV_ROOT}

# NB: We intentionally do not use `--enable-shared`, as it results in our shipped wheels for the
# PEX release using `libpython.X.Y.so.1`, which means that the PEX will not work for any consumer
# interpreters that were statically built, i.e. compiled without `--enable-shared`. See
# https://github.com/pantsbuild/pants/pull/7794.
RUN /usr/bin/scl enable devtoolset-7 -- ${PYENV_BIN} install ${PYTHON_27_VERSION}
RUN /usr/bin/scl enable devtoolset-7 -- ${PYENV_BIN} install ${PYTHON_36_VERSION}
RUN /usr/bin/scl enable devtoolset-7 -- ${PYENV_BIN} install ${PYTHON_37_VERSION}
RUN /usr/bin/scl enable devtoolset-7 -- ${PYENV_BIN} install ${PYTHON_38_VERSION}

ENV PATH "${PYENV_ROOT}/versions/${PYTHON_27_VERSION}/bin:${PATH}"
ENV PATH "${PYENV_ROOT}/versions/${PYTHON_36_VERSION}/bin:${PATH}"
ENV PATH "${PYENV_ROOT}/versions/${PYTHON_37_VERSION}/bin:${PATH}"
ENV PATH "${PYENV_ROOT}/versions/${PYTHON_38_VERSION}/bin:${PATH}"

# We install the AWS CLI for use in CI to cache assets like pants.pex.
ENV AWS_CLI_ROOT /aws-docker-build
RUN curl --fail -L "https://s3.amazonaws.com/aws-cli/awscli-bundle.zip" -o "awscli-bundle.zip" && \
  unzip awscli-bundle.zip && \
  ./awscli-bundle/install --install-dir "${AWS_CLI_ROOT}"
ENV PATH "${AWS_CLI_ROOT}/bin/:${PATH}"
# Multipart operations aren't supported for anonymous users, so we set the
# threshold high to avoid them being used automatically by the AWS CLI.
RUN aws configure set default.s3.multipart_threshold 1024MB

# Expose the installed gcc to the invoking shell.
ENTRYPOINT ["/usr/bin/scl", "enable", "devtoolset-7",  "--"]
