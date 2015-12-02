// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.runner;

import java.io.File;
import java.io.IOException;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.net.MalformedURLException;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Files;

/**
 * Helper class to run java code with too long classpath.
 * Usage: java -cp classpath_with_pants_runner
 * org.pantsbuild.tools.runner.PantsRunner
 * file_with_classpath_separated_using_os_delimiter main_class_to_execute args_to_main_class.
 */
public class PantsRunner {
  public static void main(String[] args) throws ReflectiveOperationException, IOException {
    if (args.length < 2) {
      throw new IllegalArgumentException("Should be at least two arguments to runner: " +
          "file with os delimiter separated classpath and main class to execute.");
    }
    String classpath = new String(Files.readAllBytes(new File(args[0]).toPath())).trim();
    updateClassPathProperty(classpath);
    updateClassLoader(classpath);
    String[] mainArgs = new String[args.length - 2];
    System.arraycopy(args, 2, mainArgs, 0, args.length - 2);
    runMainMethod(args[1], mainArgs);
  }

  private static void updateClassPathProperty(String classpath) {
    System.setProperty("java.class.path",
        System.getProperty("java.class.path") + File.pathSeparator + classpath);
  }

  private static void updateClassLoader(String classpath)
      throws ReflectiveOperationException, MalformedURLException {
    URLClassLoader classLoader = (URLClassLoader) PantsRunner.class.getClassLoader();
    Method addUrl = URLClassLoader.class.getDeclaredMethod("addURL", URL.class);
    addUrl.setAccessible(true);
    for (String entry : classpath.split(File.pathSeparator)) {
      addUrl.invoke(classLoader, new File(entry).toURI().toURL());
    }
  }

  private static void runMainMethod(String mainClass, String[] args)
      throws ReflectiveOperationException {
    Method main = Class.forName(mainClass).getDeclaredMethod("main", String[].class);
    if (!Modifier.isStatic(main.getModifiers())) {
      throw new IllegalArgumentException("Main class should be static.");
    }
    main.invoke(null, new Object[]{args});
  }
}
