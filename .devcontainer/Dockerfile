FROM mcr.microsoft.com/devcontainers/rust:1

RUN arch=$(arch | sed s/aarch64/arm64/ | sed s/x86_64/amd64/) && apt-get update && export DEBIAN_FRONTEND=noninteractive \
    # Install prerequisites.
    && apt-get install --no-install-recommends -y build-essential clang libffi-dev libfuse-dev libssl-dev protobuf-compiler python3-dev \
    wget checkinstall libreadline-dev libncursesw5-dev libsqlite3-dev tk-dev libgdbm-dev libc6-dev libbz2-dev zlib1g-dev \
    # Install `hyperfine` and `dbg` for debugging and benchmarking.
    # See: https://www.pantsbuild.org/stable/docs/contributions/development/debugging-and-benchmarking
    && apt-get install --no-install-recommends -y gdb python3-dbg \
    && curl -Lo /tmp/hyperfine.deb https://github.com/sharkdp/hyperfine/releases/download/v1.19.0/hyperfine_1.19.0_${arch}.deb \
    && sudo dpkg -i /tmp/hyperfine.deb \
    # Cleanup.
    && rm -rf /tmp/* \
    && apt-get autoremove -y \
    && apt-get clean all \
    && rm -rf /var/lib/apt/lists/*

# Compile python from source to add 3.9.x
RUN cd /usr/src && \
    sudo wget https://www.python.org/ftp/python/3.9.21/Python-3.9.21.tgz && \
    sudo tar xzf Python-3.9.21.tgz && \
    cd Python-3.9.21 && \
    sudo ./configure --enable-optimizations && \
    sudo make altinstall \
    && rm -rf /usr/src/Python-3.9.21

# for PEX tests we also need 3.10.x
RUN cd /usr/src && \
    sudo wget https://www.python.org/ftp/python/3.10.9/Python-3.10.9.tgz && \
    sudo tar xzf Python-3.10.9.tgz && \
    cd Python-3.10.9 && \
    sudo ./configure --enable-optimizations && \
    sudo make altinstall \
    && rm -rf /usr/src/Python-3.10.9
