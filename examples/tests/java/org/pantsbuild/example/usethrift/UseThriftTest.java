// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// Illustrate using Thrift-generated code from Java.

package org.pantsbuild.example.usethrift;

import org.junit.Test;

import org.pantsbuild.example.distance.thriftjava.Distance;
import org.pantsbuild.example.precipitation.thriftjava.Precipitation;

/* Not testing behavior; we're happy if this compiles. */
public class UseThriftTest {
  @Test
  public void makeItRain() {
    Distance notMuch = new Distance().setNumber(8).setUnit("mm");
    Precipitation sprinkle = new Precipitation().setDistance(notMuch);
  }
}

