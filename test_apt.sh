#!/usr/bin/env bash

export PANTS_DEV=1

./pants clean-all && \
./pants compile examples/src/java/com/pants/examples/annotation/main -ldebug && \
echo " " >> examples/src/java/com/pants/examples/annotation/processor/ExampleProcessor.java && \
git diff && \
./pants compile examples/src/java/com/pants/examples/annotation/main -ldebug
