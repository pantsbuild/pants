// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.testproject.reporting_example;

import java.util.HashMap;

public class Dependency {
  private static HashMap<String, String> getItems(Object items) {
    HashMap<String, String> theHash = (HashMap<String, String>) items;
    return theHash;
  }
}
