// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.resourcejar;


import com.google.common.base.Charsets;
import com.google.common.io.Resources;

import org.junit.Test;

import static org.junit.Assert.assertEquals;


/**
 * Demonstrate that instead of a directory of resources on the classpath we put a zip of the
 * resources on the classpath.
 */
public class ResourceJar {

  @Test
  public void testResourceJar() throws Exception {
    assertEquals(
      "1234567890",
      Resources.toString(
        Resources.getResource(ResourceJar.class, "resource_file.txt"), Charsets.UTF_8));
  }
}