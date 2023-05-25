# For manylinux compatibility, we build Linux wheels in a container rather than directly
# on the CI runner. This adds the AWS CLI to the standard manylinux image, which we need
# in order to publish built wheels to S3.
FROM quay.io/pypa/manylinux2014_x86_64:2023-01-03-129be5e

RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && \
    unzip awscliv2.zip && \
    ./aws/install && \
    rm -rf ./aws && \
    rm -f awscliv2.zip

RUN groupadd -g 1000 gha && \
    adduser -u 1000 -g 1000 gha

USER gha
