// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// Illustrate using Thrift-generated code from Java.

package com.pants.examples.usethrift;

import org.junit.Test;

import com.pants.examples.distance.thriftjava.Distance;
import com.pants.examples.precipitation.thriftjava.Precipitation;

/* Not testing behavior; we're happy if this compiles. */
public class UseThriftTest {
  @Test
  public void makeItRain() {
    Distance notMuch = new Distance().setNumber(8).setUnit("mm");
    Precipitation sprinkle = new Precipitation().setDistance(notMuch);
  }
}

