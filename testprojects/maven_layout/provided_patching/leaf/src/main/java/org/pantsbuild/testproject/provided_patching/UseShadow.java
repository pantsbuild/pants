// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.provided_patching;

public class UseShadow {

  public static void main(String[] args) {
    System.out.println(new Shadow().getShadowVersion() + ":" + Common.getCommonShadowVersion());
  }

}