# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Use the standard python-2.7 docker Debian Wheezy image for binary compatibility with old linux
# distros.
FROM python:2.7.13-wheezy

# Ensure Pants runs under the 2.7.13 interpreter.
ENV PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS="['CPython==2.7.13']"

# Install various things Pants requires.
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y default-jdk
