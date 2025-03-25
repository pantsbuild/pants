FROM mcr.microsoft.com/devcontainers/base:noble

ARG ARCH=${TARGETARCH:-amd64}
RUN ARCH=$(ARCH | sed s/aarch64/arm64/ | sed s/x86_64/amd64/) && apt-get update && export DEBIAN_FRONTEND=noninteractive \
    # Install prerequisites.
    && apt-get install --no-install-recommends -y build-essential clang libffi-dev libfuse-dev libssl-dev protobuf-compiler python3-dev \
    ca-certificates software-properties-common \
    # Install `hyperfine` and `dbg` for debugging and benchmarking.
    # See: https://www.pantsbuild.org/stable/docs/contributions/development/debugging-and-benchmarking
    && apt-get install --no-install-recommends -y gdb python3-dbg \
    && curl -Lo /tmp/hyperfine.deb https://github.com/sharkdp/hyperfine/releases/download/v1.19.0/hyperfine_1.19.0_${arch}.deb \
    && dpkg -i /tmp/hyperfine.deb \
    # Add deadsnakes PPA and install Python versions.
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install --no-install-recommends -y python3.8 python3.8-dev python3.8-venv \
        python3.9 python3.9-dev python3.9-venv \
        python3.10 python3.10-dev python3.10-venv \
    # Cleanup.
    && rm -rf /tmp/* \
    && apt-get autoremove -y \
    && apt-get clean all \
    && rm -rf /var/lib/apt/lists/*
