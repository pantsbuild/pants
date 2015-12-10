// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.runner.testproject;

import java.net.URL;
import java.net.URLClassLoader;
import java.util.Arrays;

public class MainClass {
  public static void main(String[] args) {
    System.out.println(DependentClass.getDependentClassMessage());
    System.out.println("Args: " + Arrays.toString(args));
    for (URL url : ((URLClassLoader) MainClass.class.getClassLoader()).getURLs()) {
      System.out.println("URL: " + url.toString().substring(url.toString().lastIndexOf("/") + 1));
    }
  }
}
