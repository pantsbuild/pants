FROM python:3.9.12-slim-buster@sha256:62ed2b347a385102d33f5e82530862359f8dc60464674d78cef844b02d150a50

RUN apt-get update && apt-get install -y \
    build-essential cmake git grpc++ libcurl4-openssl-dev libgmock-dev libgrpc++-dev \
    libgrpc-dev libgtest-dev libprotobuf-dev libssl-dev pkg-config protobuf-compiler \
    protobuf-compiler-grpc python3 python3-pip uuid-dev

COPY download_install.sh /tmp/download_install.sh
RUN chmod +x /tmp/download_install.sh && mkdir -p /out

# Install buildbox components in order.
RUN /tmp/download_install.sh buildbox-common c5a2ee2b448c636507489fd7b26a29394e3b0edb
ENV BUILDBOX_COMMON_SOURCE_ROOT=/tmp/buildbox-common
RUN /tmp/download_install.sh buildbox-worker 9565a93292b04e103d62817153553d62c6f9237e YES
RUN /tmp/download_install.sh buildbox-run-hosttools 5fc4184de288f19d40a90c6498462f57de49539d YES

# Install buildgrid.
RUN git clone https://gitlab.com/BuildGrid/buildgrid.git && \
    git -C buildgrid reset --hard 55011817110dec2478b2321ae43d835e91d78f70

RUN pip install ./buildgrid

ADD entrypoint.sh /entrypoint.sh
RUN chmod 555 /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
