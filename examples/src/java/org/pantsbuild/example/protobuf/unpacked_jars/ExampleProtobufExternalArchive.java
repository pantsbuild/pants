// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.protobuf.unpacked_jars;

import com.squareup.testing.protolib.External;

class ExampleProtobufExternalArchive {
  private ExampleProtobufExternalArchive() {
  }

  public static void main(String[] args) {
    External.ExternalMessage message = External.ExternalMessage.newBuilder().setMessageType(1)
      .setMessageContent("Hello World!").build();
    System.out.println("Message is: " + message.getMessageContent());
  }
}
