# For manylinux compatibility, we build Linux wheels in a container rather than directly
# on the CI runner.
FROM quay.io/pypa/manylinux2014_aarch64:2023-01-03-129be5e

# Add the AWS CLI, which we need in order to publish built wheels to S3.
RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o "awscliv2.zip" && \
    unzip awscliv2.zip && \
    ./aws/install && \
    rm -rf ./aws && \
    rm -f awscliv2.zip

# The Go backend is enabled, we add a synthetic target for the Go SDK, which therefore
# must be present even though wheel building does not need it.
# TODO: Make the target generator lazy, so that unused tooling doesn't have to be present.
RUN curl -LO "https://go.dev/dl/go1.17.1.linux-arm64.tar.gz" && \
    tar -C /usr/local -xzf go1.17.1.linux-arm64.tar.gz

ENV PATH="${PATH}:/usr/local/go/bin"

RUN groupadd -g 1000 gha && \
    adduser -u 1000 -g 1000 gha

USER gha
