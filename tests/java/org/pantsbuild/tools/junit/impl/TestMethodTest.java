// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import com.google.common.collect.ImmutableList;
import org.junit.Test;
import org.pantsbuild.tools.junit.lib.MockTest1;
import org.pantsbuild.tools.junit.lib.MockTest2;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

public class TestMethodTest {

  @Test
  public void testEquals() {
    TestMethod testMethod1 = new TestMethod(MockTest1.class, "method1");
    TestMethod same = new TestMethod(MockTest1.class, "method1");
    assertEquals(testMethod1, same);
  }

  @Test
  public void testCompareTo() {
    // method2 and method2 aren't really method in this class, but TestMethod doesn't know that.
    TestMethod testMethod1 = new TestMethod(MockTest1.class, "method1");
    TestMethod same = new TestMethod(MockTest1.class, "method1");
    TestMethod testMethod2 = new TestMethod(MockTest1.class, "method2");
    TestMethod testMethod3 = new TestMethod(MockTest2.class, "method1");

    assertTrue(testMethod1.compareTo(testMethod2) < 0);
    assertTrue(testMethod2.compareTo(testMethod1) > 0);
    assertTrue(testMethod1.compareTo(same) == 0);
    assertTrue(same.compareTo(testMethod1) == 0);
    assertTrue(testMethod1.compareTo(testMethod3) < 0);
    assertTrue(testMethod3.compareTo(testMethod1) > 0);
  }

  @Test
  public void testFromClass() {
    TestMethod testMethod1 = new TestMethod(MockTest1.class, "testMethod11");
    TestMethod testMethod2 = new TestMethod(MockTest1.class, "testMethod12");
    TestMethod testMethod3 = new TestMethod(MockTest1.class, "testMethod13");
    assertEquals(ImmutableList.of(testMethod1, testMethod2, testMethod3),
        TestMethod.fromClass(MockTest1.class));
  }
}
