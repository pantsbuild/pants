FROM mcr.microsoft.com/devcontainers/rust:1

RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    # Install prerequisites.
    && apt-get install --no-install-recommends -y build-essential clang libffi-dev libfuse-dev libssl-dev protobuf-compiler python3-dev \
    # Install `hyperfine` and `dbg` for debugging and benchmarking.
    # See: https://www.pantsbuild.org/stable/docs/contributions/development/debugging-and-benchmarking
    && apt-get install --no-install-recommends -y gdb python3-dbg \
    && curl -Lo /tmp/hyperfine.deb https://github.com/sharkdp/hyperfine/releases/download/v1.19.0/hyperfine_1.19.0_amd64.deb \
    && sudo dpkg -i /tmp/hyperfine.deb \
    # Cleanup.
    && rm -rf /tmp/* \
    && apt-get autoremove -y \
    && apt-get clean all \
    && rm -rf /var/lib/apt/lists/*
