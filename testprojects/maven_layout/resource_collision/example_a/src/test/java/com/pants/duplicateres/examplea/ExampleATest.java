// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.duplicateres.examplea;

import com.pants.duplicateres.lib.CheckRes;
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
    CheckRes.assertResource("/com/pants/duplicateres/duplicated_resource.txt",
        "resource from example a");
  }
}
