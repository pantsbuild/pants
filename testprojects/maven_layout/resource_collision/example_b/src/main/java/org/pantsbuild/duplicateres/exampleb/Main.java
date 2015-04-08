// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.duplicateres.exampleb;

import org.pantsbuild.duplicateres.lib.CheckRes;
import java.io.IOException;

public class Main {
  private static String RESOURCE_PATH = "/org/pantsbuild/duplicateres/duplicated_resource.txt";
  private static String EXPECTED = "resource from example b";

  public static void main(String args[]) throws IOException {
    CheckRes.assertResource(RESOURCE_PATH, EXPECTED);
    System.out.println("Hello world!: " + CheckRes.getResourceAsString(RESOURCE_PATH));
  }
}
