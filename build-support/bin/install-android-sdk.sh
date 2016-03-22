#!/usr/bin/env bash
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Install the Android SDK for the Pants Android contrib module.

# SDK_INSTALL_LOCATION and ANDROID_HOME set in travis.yaml.
ANDROID_SDK_URL="http://dl.google.com/android/android-sdk_r24.4.1-linux.tgz"
SDK_FILE=$(basename "$ANDROID_SDK_URL")

# The debug.keystore has a well-known definition and location.
KEYSTORE_LOCATION="$HOME"/.android

# Add SDKs as needed.
declare -a SDK_MODULES=(android-19 \
                        android-20 \
                        android-21 \
                        android-22 \
                        build-tools-19.1.0 \
                        extra-android-support \
                        extra-google-m2repository \
                        extra-android-m2repository \
                        platform-tools)

mkdir -p "$SDK_INSTALL_LOCATION"
mkdir -p "$KEYSTORE_LOCATION"


function join { local IFS="$1"; shift; echo "$*"; }
MODULE_LIST=$(join , ${SDK_MODULES[@]})

echo "Downloading $ANDROID_SDK_URL..."
SDK_ARCHIVE_LOCATION="$SDK_INSTALL_LOCATION"/"$SDK_FILE"

wget -nc "$ANDROID_SDK_URL" -O "$SDK_ARCHIVE_LOCATION"
tar -C "$SDK_INSTALL_LOCATION" -xf "$SDK_ARCHIVE_LOCATION"

# Spamming 'y' was failing non-deterministically so sleep between echos.
( sleep 5 && while [ 1 ]; do sleep 1; echo y; done ) | \
    "$ANDROID_HOME"/tools/android update sdk -u --all --filter "$MODULE_LIST"

# Generate well known debug.keystore if the SDK hasn't created it.
DEBUG_KEYSTORE="$KEYSTORE_LOCATION"/debug.keystore
if [[ ! -f "$DEBUG_KEYSTORE" ]]; then
    keytool -genkey -v -keystore "$KEYSTORE_LOCATION"/debug.keystore -alias androiddebugkey -storepass android  \
        -keypass android -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Android Debug,O=Android,C=US"
fi
