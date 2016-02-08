// Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.syntheticjar.util;

import java.net.URL;
import java.net.URLClassLoader;
import java.util.Arrays;

public class Util {
  public static void failIfSyntheticJar() {
    URL[] urls = ((URLClassLoader) Thread.currentThread().getContextClassLoader()).getURLs();
    if (urls.length == 1) {
      throw new IllegalStateException("Synthetic jar run is detected, classpath: " +
          Arrays.toString(urls));
    }
  }
}
