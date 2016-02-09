// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.syntheticjar.util;

import java.net.URL;
import java.net.URLClassLoader;
import java.util.Arrays;

public class Util {
  public static void detectSyntheticJar() {
    URL[] urls = ((URLClassLoader) Thread.currentThread().getContextClassLoader()).getURLs();
    String detectStatus = urls.length == 1 ? "detected" : "not detected";
    System.out.println("Synthetic jar run is " + detectStatus + ", classpath: " +
      Arrays.toString(urls));
  }
}
