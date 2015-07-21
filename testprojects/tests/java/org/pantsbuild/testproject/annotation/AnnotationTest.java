// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.annotation;

import org.junit.Test;

import static org.junit.Assert.assertTrue;

/**
 * This test confirms that resources generated for test targets don't interfere with JUnit.
 *
 * See the BUILD file for this target.
 */
public class AnnotationTest {
  @Deprecated
  @Test
  public void testAnnotation() {
    assertTrue(1 == Integer.parseInt("1"));
  }
}
