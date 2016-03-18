// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import org.junit.Assert;
import org.junit.Ignore;
import org.junit.Test;

public class XmlReportAllIgnoredTest {
  @Ignore
  @Test
  public void testXmlIgnored() {
    Assert.assertTrue(true);
  }

  @Ignore
  @Test
  public void testXmlIgnoredAgain() {
    Assert.assertTrue(true);
  }
}
