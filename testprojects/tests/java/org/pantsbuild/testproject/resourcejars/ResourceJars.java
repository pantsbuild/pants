// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.resourcejars;

import java.net.URL;
import java.net.URLClassLoader;
import org.junit.Test;

import java.util.regex.Matcher;
import java.util.regex.Pattern;


import static org.junit.Assert.assertTrue;

/**
 * Demonstrate that instead of a directory of resources on the classpath we put a zip of the
 * resources on the classpath.
 */

public class ResourceJars {

  @Test
  public void testResourceJars() {
    ClassLoader cl = ClassLoader.getSystemClassLoader();
    URL[] urls = ((URLClassLoader) cl).getURLs();
    String zip = ".*zip_resources/prepare_zips/testprojects.tests.resources.resources.zip$";
    Pattern p = Pattern.compile(zip);
    boolean found = false;
    for (URL url : urls) {
      String f = url.getFile();
      if (p.matcher(f).matches()) {
        found = true;
        break;
      }
    }
    assertTrue("could not find " + zip, found);
  }
}
