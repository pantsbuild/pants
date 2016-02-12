// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.syntheticjar.run;

import org.junit.Test;

public class SyntheticJarTest {
  @Test
  public void testSyntheticJar() {
    org.pantsbuild.testproject.syntheticjar.util.Util.detectSyntheticJar();
  }
}
