// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import com.squareup.burst.BurstJUnit4;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(BurstJUnit4.class)
public class MockBurstParallelClassesAndMethodsTest2 {
  private final FruitType fruitType;
  public enum FruitType {
    APPLE, BANANA, CHERRY
  }

  public MockBurstParallelClassesAndMethodsTest2(FruitType fruitType) {
    this.fruitType = fruitType;
  }

  @Test
  public void bpcamtest1() throws Exception {
    MockBurstParallelClassesAndMethodsTest1.awaitLatch("bpcamtest2:" + fruitType.name());
  }
}
