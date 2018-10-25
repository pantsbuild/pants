FROM ubuntu:rolling

RUN apt update && apt upgrade -y && apt install -y \
    git \
    python2 \
    python3 \
    curl \
    build-essential \
    python2-dev \
    python3-dev \
    default-jdk-headless \
    language-pack-en \
    libssl-dev

RUN git clone https://github.com/pantsbuild/pants.git
WORKDIR pants

ENV LC_ALL=en_US.UTF-8
ENV LANG=en_US.UTF-8

RUN ./pants clean-all

RUN mkdir /results

COPY run_python3_tests.sh entrypoint.sh
RUN chmod +x entrypoint.sh

ENTRYPOINT ./entrypoint.sh
