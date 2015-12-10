// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.runner;

import java.io.File;
import java.io.IOException;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.net.MalformedURLException;
import java.net.URISyntaxException;
import java.net.URL;
import java.net.URLClassLoader;
import java.util.jar.JarFile;
import java.util.jar.Manifest;

/**
 * Helper class for running java code using synthetic jar.
 * In some cases when code deal with classloaders, running this code
 * using synthetic jar can fail. Running this cases using this Runner
 * most likely fix all problems with classloaders.
 */
public class PantsRunner {
  public static void main(String[] args) throws Exception {
    if (args.length == 0) {
      System.out.println("Usage: java -cp synthetic_jar " +
          "org.pantsbuild.tools.runner.PantsRunner " +
          "main_class args.\n" +
          "Synthetic jar should contain manifest file " +
          "with properly declared Class-Path property.");
      System.exit(1);
    }
    String classpath = readClasspath();
    updateClassPathProperty(classpath);
    updateClassLoader(getClassLoader(), classpath);
    String[] mainArgs = new String[args.length - 1];
    System.arraycopy(args, 1, mainArgs, 0, args.length - 1);
    runMainMethod(args[0], mainArgs);
  }

  private static String readClasspath() throws IOException, URISyntaxException {
    URL[] urls = getClassLoader().getURLs();
    if (urls.length != 1 || !urls[0].getProtocol().equals("file") ||
        !urls[0].toString().endsWith(".jar")) {
      throw new IllegalArgumentException("Should be exactly one jar file in the classpath.");
    }
    JarFile jar = new JarFile(new File(urls[0].toURI()));
    Manifest manifest = jar.getManifest();
    if (manifest == null) {
      throw new IllegalArgumentException("Supplied jar file doesn't contains " +
          "manifest file.");
    }
    String classpath = manifest.getMainAttributes().getValue("Class-Path");
    if (classpath == null) {
      throw new IllegalArgumentException("Supplied jar file's manifest " +
          "doesn't contains Class-Path section.");
    }
    return classpath.replace(" ", File.pathSeparator);
  }

  private static URLClassLoader getClassLoader() {
    // Using context classloader here as it should be application one on the startup and
    // because it's simple to mock context class loader in tests.
    return (URLClassLoader) Thread.currentThread().getContextClassLoader();
  }

  private static void updateClassPathProperty(String classpath) {
    System.setProperty("java.class.path",
        System.getProperty("java.class.path") + File.pathSeparator + classpath);
  }

  private static void updateClassLoader(URLClassLoader classLoader, String classpath)
      throws ReflectiveOperationException, MalformedURLException {
    Method addUrl = URLClassLoader.class.getDeclaredMethod("addURL", URL.class);
    addUrl.setAccessible(true);
    for (String entry : classpath.split(File.pathSeparator)) {
      addUrl.invoke(classLoader, new File(entry).toURI().toURL());
    }
  }

  private static void runMainMethod(String mainClass, String[] args)
      throws ReflectiveOperationException {
    Method main = Class.forName(mainClass, true, getClassLoader()).
        getDeclaredMethod("main", String[].class);
    if (!Modifier.isStatic(main.getModifiers())) {
      throw new IllegalArgumentException("Method 'main' for " + mainClass + " is not static.");
    }
    main.invoke(null, new Object[]{args});
  }
}
