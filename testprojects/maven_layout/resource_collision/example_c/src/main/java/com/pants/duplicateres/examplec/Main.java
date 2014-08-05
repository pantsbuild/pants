// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package com.pants.duplicateres.examplec;

import com.pants.duplicateres.lib.CheckRes;
import java.io.IOException;

public class Main {
  private static String RESOURCE_PATH = "/com/pants/duplicateres/duplicated_resource.txt";
  private static String EXPECTED = "resource from example c";

  public static void main(String args[]) throws IOException {
    CheckRes.assertResource(RESOURCE_PATH, EXPECTED);
    System.out.println("Hello world!: " + CheckRes.getResourceAsString(RESOURCE_PATH));
  }
}
