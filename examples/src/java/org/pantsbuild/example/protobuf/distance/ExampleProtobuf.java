// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.protobuf.distance;

import org.pantsbuild.example.distance.Distances;

class ExampleProtobuf {

  private ExampleProtobuf() {
  }

  public static void main(String[] args) {
      System.out.println(Distances.Distance.newBuilder().setNumber(12).setUnit("parsecs").build());
  }
}
