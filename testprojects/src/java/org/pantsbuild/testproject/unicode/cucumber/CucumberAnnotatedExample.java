// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.unicode.cucumber;

import cucumber.api.java.zh_cn.假如;

/**
 * References a class in an external dependency with a non-ascii encodable unicode name.
 */
public class CucumberAnnotatedExample {

  public CucumberAnnotatedExample() {
  }

  @假如("祝你今天愉快!")
  public String pleasantry() {
    return "Have a nice day!";
  }
}
