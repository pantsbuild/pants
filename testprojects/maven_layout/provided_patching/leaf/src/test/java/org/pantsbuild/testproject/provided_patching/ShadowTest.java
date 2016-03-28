// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.provided_patching;

import org.junit.Test;
import static org.junit.Assert.*;

public class ShadowTest{

  @Test public void testShadowVersion() {
    assertEquals(new Shadow().getShadowVersion(), "Shadow Two");
  }

}