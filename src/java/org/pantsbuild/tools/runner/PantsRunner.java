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
import java.util.ArrayList;
import java.util.List;
import java.util.jar.JarFile;
import java.util.jar.Manifest;

import com.google.common.base.Joiner;
import com.google.common.base.Splitter;
import com.google.common.collect.Lists;

/**
 * Helper class for running java code using synthetic jar.
 * In some cases when code deal with classloaders, running this code
 * using synthetic jar can fail. Running this cases using this Runner
 * most likely fix all problems with classloaders.
 */
public class PantsRunner {

  private static final String JAVA_CLASS_PATH = "java.class.path";

  public static void main(String[] args) throws Exception {
    if (args.length == 0) {
      System.out.println("Usage: java -cp synthetic_jar " +
          "org.pantsbuild.tools.runner.PantsRunner " +
          "main_class args.\n" +
          "Synthetic jar should contain manifest file " +
          "with properly declared Class-Path property.");
      System.exit(1);
    }
    List<File> classpath = readClasspath();
    updateClassPathProperty(classpath);
    updateClassLoader(classpath);
    String[] mainArgs = new String[args.length - 1];
    System.arraycopy(args, 1, mainArgs, 0, args.length - 1);
    runMainMethod(args[0], mainArgs);
  }

  private static List<File> readClasspath() throws IOException {
    List<String> paths = Lists.newArrayList(Splitter.on(File.pathSeparatorChar)
            .split(System.getProperty(JAVA_CLASS_PATH)));
    if (paths.size() != 1 || !paths.get(0).endsWith(".jar")) {
      throw new IllegalArgumentException("Should be exactly one jar file in the classpath.");
    }
    File jarFile = new File(paths.get(0));
    JarFile jar = new JarFile(jarFile);
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
    List<File> classpathURLs = new ArrayList<>();
    classpathURLs.add(jarFile);
    for (String path : classpath.split("\\s")) {
      classpathURLs.add(new File(jarFile.getParent(), path));
    }
    return classpathURLs;
  }

  private static ClassLoader getClassLoader() {
    // Using context classloader here as it should be application one on the startup and
    // because it's simple to mock context class loader in tests.
    return Thread.currentThread().getContextClassLoader();
  }

  private static void updateClassPathProperty(List<File> classpath) {
    System.setProperty(JAVA_CLASS_PATH,
            System.getProperty(JAVA_CLASS_PATH) + File.pathSeparator +
                    Joiner.on(File.pathSeparatorChar).join(classpath));
  }

  private static void updateClassLoader(List<File> classpath)
          throws MalformedURLException {
    List<URL> classpathUrls = new ArrayList<>();
    for (File file : classpath) {
      classpathUrls.add(file.toURI().toURL());
    }
    Thread.currentThread().setContextClassLoader(
            URLClassLoader.newInstance(classpathUrls.toArray(new URL[0])));
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
