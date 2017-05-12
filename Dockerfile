FROM ubuntu:15.04

RUN apt-get update && apt-get install -y \
  build-essential \
  curl \
  git \
  openjdk-8-jdk \
  python-dev

RUN locale-gen en_US.UTF-8 && dpkg-reconfigure locales

