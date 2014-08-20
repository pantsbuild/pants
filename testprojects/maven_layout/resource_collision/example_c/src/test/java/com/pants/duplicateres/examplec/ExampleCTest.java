// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.duplicateres.examplec;

import com.pants.duplicateres.lib.CheckRes;
import org.junit.Test;

import static org.junit.Assert.assertTrue;

/**
 * Example C should contain only one copy of 'duplicate_resource.txt'
 * on the classpath.
 */
public class ExampleCTest {

  @Test
  public void testResource() throws Exception {
    CheckRes.assertResource("/com/pants/duplicateres/duplicated_resource.txt",
        "resource from example c");
  }
}
