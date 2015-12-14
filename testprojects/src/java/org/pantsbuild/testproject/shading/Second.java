// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.shading;

/**
 * This is the not-main file in a tiny library made to test shading of 3rdparty libraries.
 */
public class Second {

  private int writeOnlyInteger = 0;

  /**
   * The behavior of this function is irrelevant, we just want to make sure it can be called at all.
   * @param i
   */
  public void write(int i) {
    this.writeOnlyInteger = i;
  }

}
