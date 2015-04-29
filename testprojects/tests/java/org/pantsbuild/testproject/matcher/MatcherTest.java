// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.matcher;

import org.hamcrest.BaseMatcher;
import org.hamcrest.Description;
import org.junit.Test;

import static org.hamcrest.CoreMatchers.containsString;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertThat;
import static org.junit.Assert.assertTrue;

/**
 * This test insures that the junit and hamcrest classes work for a junit test.
 */
public class MatcherTest {

  class FooMatcher extends BaseMatcher<String> {

    @Override public boolean matches(Object o) {
      assertTrue(String.class.isInstance(o));
      String value = (String) o;
      return value.contains("foo");
    }

    @Override public void describeTo(Description description) {
      description.appendText(this.getClass().getSimpleName());
    }
  }

  @Test
  public void testMatcher() {
    FooMatcher matcher = new FooMatcher();
    assertTrue(matcher.matches("foobar"));
    assertFalse(matcher.matches("Hello World!"));
  }

  /**
   * This test fails if the org.hamcrest classes are shaded in junit runner
   */
  @Test
  public void testAssertThat() {
    assertThat("Give me some food", containsString("foo"));
  }
}
