// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.io.IOException;

/**
 * Provides contents of the output streams captured from a test class run.
 */
interface StreamSource {

  /**
   * Returns the contents of STDOUT from a test class run.
   *
   * @param testClass The test class to retrieve captured output for.
   * @return The captured STDOUT stream.
   * @throws IOException If there is a problem retrieving the output.
   */
  byte[] readOut(Class<?> testClass) throws IOException;

  /**
   * Returns the contents of STDERR from a test class run.
   *
   * @param testClass The test class to retrieve captured output for.
   * @return The captured STDERR stream.
   * @throws IOException If there is a problem retrieving the output.
   */
  byte[] readErr(Class<?> testClass) throws IOException;
}
