// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.duplicateres.examplec;

import org.pantsbuild.duplicateres.lib.CheckRes;
import org.junit.Test;

import static org.junit.Assert.assertTrue;

/**
 * Example C should contain only one copy of 'duplicate_resource.txt'
 * on the classpath.
 */
public class ExampleCTest {

  @Test
  public void testResource() throws Exception {
    CheckRes.assertResource("/org/pantsbuild/duplicateres/duplicated_resource.txt",
        "resource from example c");
  }
}
