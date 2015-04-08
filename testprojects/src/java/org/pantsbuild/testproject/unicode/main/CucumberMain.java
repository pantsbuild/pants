// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.unicode.main;

import org.pantsbuild.testproject.unicode.cucumber.CucumberAnnotatedExample;
import org.pantsbuild.testproject.unicode.shapeless.ShapelessExample;

/**
 * This does not do anything usefule with the Cucumber library, but uses it as an external
 * dep to demonstrate that pants works with non-ascii unicode classes.
 */
public class CucumberMain {

  public static void main(String[] args) {
    CucumberAnnotatedExample example = new CucumberAnnotatedExample();
    System.out.println(example.pleasantry());
    System.out.println(ShapelessExample.greek());
  }
}
