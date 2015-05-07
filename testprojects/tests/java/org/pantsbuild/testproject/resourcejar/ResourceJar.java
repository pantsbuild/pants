// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.resourcejar;

import java.net.URL;
import java.net.URLClassLoader;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import com.google.common.base.Charsets;
import com.google.common.io.Resources;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;


/**
 * Demonstrate that instead of a directory of resources on the classpath we put a zip of the
 * resources on the classpath.
 */
public class ResourceJar {

  @Test
  public void testResourceJar() throws Exception {
    // Test part 1: make sure the resource jar is named expectedly and does exist.
    ClassLoader cl = ClassLoader.getSystemClassLoader();
    URL[] urls = ((URLClassLoader) cl).getURLs();
    String jar = ".*resources/prepare/"
        + "testprojects.tests.resources.org.pantsbuild.testproject.resourcejar.resourcejar.jar$";
    Pattern p = Pattern.compile(jar);
    String urls_print = "";
    boolean found = false;
    for (URL url : urls) {
      String f = url.getFile();
      urls_print += f + "\n";
      if (p.matcher(f).matches()) {
        found = true;
        break;
      }
    }
    assertTrue("\ncould not find " + jar + " in:\n" + urls_print, found);

    // Test part 2: make sure it can be used transparently as if the resource isn't jarred.
    assertEquals(
      "1234567890",
      Resources.toString(
        Resources.getResource(ResourceJar.class, "resource_file.txt"), Charsets.UTF_8));
  }
}