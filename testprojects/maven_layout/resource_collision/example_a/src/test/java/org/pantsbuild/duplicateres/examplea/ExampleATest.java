// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.duplicateres.examplea;

import org.pantsbuild.duplicateres.lib.CheckRes;
import org.junit.Test;

import static org.junit.Assert.assertTrue;

/**
 * Example A should contain 3 copies of 'duplicate_resource.txt'
 * on the classpath.  The one associated with the 'examplea' target should
 * override the ones defined in 'exampleb' and 'examplec'
 */
public class ExampleATest {

  @Test
  public void testResource() throws Exception {
    CheckRes.assertResource("/org/pantsbuild/duplicateres/duplicated_resource.txt",
        "resource from example a");
  }
}
