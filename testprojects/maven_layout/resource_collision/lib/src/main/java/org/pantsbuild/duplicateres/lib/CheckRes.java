// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.duplicateres.lib;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;

/**
 * Utility class to Load a resource from the classloader
 */
public class CheckRes {

  /**
   * Lookup the specified resource path using the default classloader and extract
   * its contents as a string.
   */
  public static String getResourceAsString(String path) throws IOException {
    StringBuilder sb = new StringBuilder();
    BufferedReader reader = new BufferedReader(new InputStreamReader(
        CheckRes.class.getResourceAsStream(path)));
    String result;
    while ((result = reader.readLine()) != null) {
      sb.append(result);
    }
    return sb.toString();
  }

  /**
   * Lookup the contents of the specified resource path and compare it to an expected value.
   * @throws {@link AssertionError}
   */
  public static void assertResource(String path, String value) throws IOException {
   String result = getResourceAsString(path);
    if (!result.equals(value)) {
      throw new AssertionError("FAILURE: Expected '" + value + "' Got: '" + result + "'");
    }
  }

  private CheckRes() {
    // Utility class, do not instantiate
  }
}
