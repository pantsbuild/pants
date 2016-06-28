package org.pantsbuild.tools.junit.lib;

import com.squareup.burst.BurstJUnit4;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(BurstJUnit4.class)
public class MockBurstTest {

  private final QuarkType quarkType;
  public enum QuarkType {
    UP, DOWN, STRANGE, CHARM, TOP, BOTTOM
  }

  public MockBurstTest(QuarkType quarkType) {
    this.quarkType = quarkType;
  }

  @Test
  public void btest1() {
    TestRegistry.registerTestCall("btest1:" + quarkType.name());
  }
}
