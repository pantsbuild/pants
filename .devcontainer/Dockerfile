FROM mcr.microsoft.com/devcontainers/base:noble

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /usr/local/bin/

# Install uv-managed Pythons to a shared location (not root's home dir), so that they are
# accessible to the `vscode` user, and link their executables (e.g., `python3.9`) onto the PATH.
ENV UV_PYTHON_INSTALL_DIR=/opt/uv/python \
    UV_PYTHON_BIN_DIR=/usr/local/bin

# Put the `python` and `python3` of 3.14.9 and then 3.14.9t on the PATH, ahead of the system
# `/usr/bin/python3`, so that Pants can discover both. System tools that reference
# `/usr/bin/python3` directly are unaffected.
ENV PATH=/opt/python/3.14/bin:/opt/python/3.14t/bin:$PATH

RUN arch=$(arch | sed s/aarch64/arm64/ | sed s/x86_64/amd64/) && apt-get update && export DEBIAN_FRONTEND=noninteractive \
    # Install prerequisites.
    && apt-get install --no-install-recommends -y build-essential clang libffi-dev libfuse-dev libssl-dev protobuf-compiler python3-dev \
    ca-certificates lz4 \
    # Install `hyperfine` and `dbg` for debugging and benchmarking.
    # See: https://www.pantsbuild.org/stable/docs/contributions/development/debugging-and-benchmarking
    && apt-get install --no-install-recommends -y gdb python3-dbg \
    && curl -Lo /tmp/hyperfine.deb https://github.com/sharkdp/hyperfine/releases/download/v1.19.0/hyperfine_1.19.0_${arch}.deb \
    && dpkg -i /tmp/hyperfine.deb \
    # Install the Python versions used in CI (see `_BASE_PYTHON_VERSIONS` in
    # src/python/pants_release/generate_github_workflows.py), except for 3.7, which uv can't install.
    # Note that 3.14.9 must match the version in the export paths in devcontainer.json.
    && uv python install 3.8 3.9 3.10 3.11 3.12 3.13 3.14.9 3.14.9t \
    # Create stable, arch-independent links to the 3.14 installations, whose bin dirs are on the PATH.
    && mkdir -p /opt/python \
    && ln -s "$(dirname "$(dirname "$(uv python find --managed-python 3.14.9)")")" /opt/python/3.14 \
    && ln -s "$(dirname "$(dirname "$(uv python find --managed-python 3.14.9t)")")" /opt/python/3.14t \
    # Install `py-spy` and `memray` for CPU and memory profiling.
    # See: https://www.pantsbuild.org/stable/docs/contributions/development/debugging-and-benchmarking
    && UV_TOOL_DIR=/opt/uv/tools UV_TOOL_BIN_DIR=/usr/local/bin uv tool install --python 3.14.9 py-spy \
    && UV_TOOL_DIR=/opt/uv/tools UV_TOOL_BIN_DIR=/usr/local/bin uv tool install --python 3.14.9 memray \
    # Cleanup.
    && uv cache clean \
    && rm -rf /tmp/* \
    && apt-get autoremove -y \
    && apt-get clean all \
    && rm -rf /var/lib/apt/lists/*
