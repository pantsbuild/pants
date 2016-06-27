package org.pantsbuild.tools.junit.lib;

import com.squareup.burst.BurstJUnit4;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.pantsbuild.junit.annotations.TestParallelClassesAndMethods;

import static org.junit.Assert.assertTrue;

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
