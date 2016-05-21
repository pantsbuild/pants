#!/bin/bash
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# This script assumes an Ubuntu 16.04 LTS base image.
set -o errexit
set -o pipefail

export DEBIAN_FRONTEND=noninteractive

# Ensure we have `add-apt-repository`.
sudo apt-get -y install software-properties-common

# Pants itself, python backend tests, jenkins-slave-connect.
# ===
sudo add-apt-repository -y --update ppa:fkrull/deadsnakes
PYTHONS=(
  # Without this we only have binaries for `python2.7` and `python3`,
  # but no `python` link.
  python-minimal

  # 2.6 is needed for unit tests that exercise platform constraints.
  python2.6
  python2.6-dev

  python2.7
  python2.7-dev

  python3.5
  python3.5-dev

  pypy
  pypy-dev
)
sudo apt-get -y install ${PYTHONS[@]}

# JVM backend and jenkins-slave-connect.
# ===
sudo add-apt-repository -y --update ppa:openjdk-r/ppa
OPEN_JDKS=(
  # Unfortunately there is no headless package for OpenJDK 7.
  openjdk-7-jdk

  openjdk-8-jdk-headless
  openjdk-9-jdk-headless
)
sudo apt-get -y install ${OPEN_JDKS[@]}

sudo add-apt-repository -y --update ppa:webupd8team/java
ORACLE_JDKS=(
  oracle-java6-installer
  oracle-java7-installer
  oracle-java8-installer
)
for jdk in "${ORACLE_JDKS[@]}"; do
  echo ${jdk} shared/accepted-oracle-license-v1-1 select true | \
    sudo /usr/bin/debconf-set-selections
done
sudo apt-get -y install ${ORACLE_JDKS[@]}

sudo update-java-alternatives --set java-1.8.0-openjdk-amd64

# C/C++ contrib backend.
# ===
sudo apt-get -y install g++

# CI scripts and miscellaneous tasks.
# ===
# NB: Many of these packages come in the base image but are spelled out
# explicity here for completeness.
MISC=(
  coreutils # This provides tr, cut, etc.
  gawk
  grep
  sed
  curl
  wget
  openssl # Used for md5 hashing.
  perl # Needed by sloccount.
  git
)
sudo apt-get -y install ${MISC[@]}

# Finally, top off all our packages.
sudo apt-get -y update
sudo apt-get -y upgrade

