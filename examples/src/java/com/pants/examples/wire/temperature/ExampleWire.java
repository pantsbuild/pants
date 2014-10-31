// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.examples.wire.temperature;

import com.pants.examples.temperature.Temperature;

/**
 * Simple example of creating a message with Wire and printing out its contents.
 */
class ExampleWire {

  private ExampleWire() {
  }

  public static void main(String[] args) {
    Temperature temp = new Temperature.Builder().unit("celsius").number((long) 19).build();
    System.out.println(temp.number + " degrees " + temp.unit);
  }
}
