#!/usr/bin/env bash
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Install the Android SDK for the Pants Android contrib module.

set -e

# ANDROID_SDK_INSTALL_LOCATION and ANDROID_HOME set in travis.yaml.
ANDROID_SDK_URL="http://dl.google.com/android/android-sdk_r24.4.1-linux.tgz"
SDK_FILE=$(basename "$ANDROID_SDK_URL")
SDK_ARCHIVE_LOCATION="$ANDROID_SDK_INSTALL_LOCATION/$SDK_FILE"

# The debug.keystore has a well-known definition and location.
KEYSTORE_LOCATION="$HOME/.android"

# Add SDKs as needed.
SDK_MODULES=(
  android-19
  android-20
  android-21
  android-22
  build-tools-19.1.0
  extra-android-support
  extra-google-m2repository
  extra-android-m2repository
  platform-tools
)

FILTER=$(echo ${SDK_MODULES[@]} | tr ' ' ,)

if [[ ! -f "$SDK_ARCHIVE_LOCATION.processed" || "$FILTER" != "$(cat $SDK_ARCHIVE_LOCATION.processed)" ]]; then
  mkdir -p "$ANDROID_SDK_INSTALL_LOCATION"
  cd "$ANDROID_SDK_INSTALL_LOCATION"
  echo "Downloading $ANDROID_SDK_URL..."
  wget -c "$ANDROID_SDK_URL"
  tar -xf "$SDK_ARCHIVE_LOCATION"

  echo y | "$ANDROID_HOME/tools/android" update sdk -u --all --filter "$FILTER"

  # Generate well known debug.keystore if the SDK hasn't created it.
  DEBUG_KEYSTORE="$KEYSTORE_LOCATION/debug.keystore"
  if [[ ! -f "$DEBUG_KEYSTORE" ]]; then
    mkdir -p "$KEYSTORE_LOCATION"
    keytool -genkey -v -keystore "$KEYSTORE_LOCATION/debug.keystore" -alias androiddebugkey -storepass android  \
      -keypass android -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Android Debug,O=Android,C=US"
  fi

  # Commit the transaction.
  echo "$FILTER" > "$SDK_ARCHIVE_LOCATION.processed"
else
  echo "$SDK_ARCHIVE_LOCATION is already installed with modules:"
  for module in "${SDK_MODULES[@]}"; do
    echo "  $module"
  done
fi
