// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.lib;

import javax.net.ssl.SSLSession;
import org.junit.Assert;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.mockito.Mock;
import org.mockito.runners.MockitoJUnitRunner;

import static org.mockito.Mockito.when;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 */
@RunWith(MockitoJUnitRunner.class)
public class XmlReportMockitoStubbingTest {
  @Mock SSLSession sslSession;

  @Test
  public void testUnnecesaryMockingError() {
    when(sslSession.getCipherSuite()).thenReturn("cipher");
    Assert.assertTrue(true);
  }
}
