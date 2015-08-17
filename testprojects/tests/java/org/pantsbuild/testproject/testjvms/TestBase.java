// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.testjvms;

import static org.junit.Assert.assertEquals;

/**
 * Base class for testing what version of java is running.
 * */
public class TestBase {
  public void assertJavaVersion(String expected) {
    String version = System.getProperty("java.version");
    version = version.substring(0, version.indexOf('.', version.indexOf('.')+1));
    assertEquals(expected, version);
  }
}
