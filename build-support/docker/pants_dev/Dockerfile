# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# When developing Pants itself, errors sometimes manifest only on Linux.
# However many developers work on MacOS and cannot reproduce such problems.
# Docker provides a convenient way to access a Linux shell.

# This Dockerfile builds a lightweight image that contains a bootstrapped
# Pants repo, suitable for running Pants's own tests in.

# To build this image:
#   docker build -t pants_dev build-support/docker/pants_dev
#   TBD: Push to a pants account on dockerhub.

# To use on MacOS:
#   - Install Docker for Mac (https://docs.docker.com/docker-for-mac/).
#   - docker run -ti pants_dev

# TODO: In the future this (or something like it) could be used to speed
# up CIs, which currently have to do a lot of bootstrapping every time.

# Note that we use Alpine Linux rather than, say, Ubuntu, because of its tiny size
# and very snappy package installation.  We may need to re-think this, if it turns
# out that running Pants on Alpine isn't adequately representative of the generic
# Pants-on-Linux experience.

# Installing JDK8 on Alpine Linux is a little convoluted,
# so we start from an image that already includes it.
FROM anapsix/alpine-java:8_jdk

# Install various things Pants requires.
RUN apk update && apk add bash curl gcc git libffi-dev linux-headers musl-dev openssl python python-dev

# Clone the pantsbuild repo and bootstrap Pants in it.
RUN git clone https://github.com/pantsbuild/pants.git && cd /pants && ./pants goals

CMD bash

