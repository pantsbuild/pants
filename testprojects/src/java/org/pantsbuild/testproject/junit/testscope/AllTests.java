// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.junit.testscope;

import org.junit.Test;
import static org.junit.Assert.*;

public class AllTests {
  @Test
  public void testLibrary() {
    assertTrue("Not able to load SomeFileLibrary!", CheckForLibrary.check());
  }
}
