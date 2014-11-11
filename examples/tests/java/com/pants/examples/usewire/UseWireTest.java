// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// Illustrate using Wire-generated code from Java.

package com.pants.examples.usewire;

import org.junit.Assert;
import org.junit.Test;

import com.pants.examples.temperature.Temperature;

public class UseWireTest {
  @Test
  public void checkTemperatureExistence() {
    String value = new Temperature.Builder().unit("celsius").number((long) 19).build().toString();
    Assert.assertTrue("Temperatures string value (" + value + ")", value.contains("19"));
  }
}

