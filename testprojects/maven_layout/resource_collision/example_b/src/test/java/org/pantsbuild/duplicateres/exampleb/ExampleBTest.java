// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.duplicateres.exampleb;

import org.pantsbuild.duplicateres.lib.CheckRes;
import org.junit.Test;

import static org.junit.Assert.assertTrue;

/**
 * Example B should contain  2 copies of 'duplicate_resource.txt'
 * on the classpath.  The one associated with the 'exampleb' target should
 * override the one in 'examplec'
 */
public class ExampleBTest {

  @Test
  public void testResource() throws Exception {
    CheckRes.assertResource("/org/pantsbuild/duplicateres/duplicated_resource.txt",
        "resource from example b");
  }
}
