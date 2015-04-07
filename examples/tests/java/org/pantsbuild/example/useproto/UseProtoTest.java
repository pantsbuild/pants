// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// Illustrate using Proto-generated code from Java.

package org.pantsbuild.example.useproto;

import org.junit.Assert;
import org.junit.Test;

import org.pantsbuild.example.distance.Distances;

public class UseProtoTest {
  @Test
  public void checkDistanceExistence() {
    String value = Distances.Distance.newBuilder().setNumber(12).setUnit("parsecs").build()
        .toString();
    Assert.assertTrue("Distances string value (" + value + ")", value.contains("12"));
  }
}

