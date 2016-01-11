package org.pantsbuild.testproject.depman;

import java.io.IOException;
import java.net.URL;
import java.net.URLClassLoader;
import java.util.jar.JarInputStream;
import java.util.jar.Manifest;

/**
 * This is used to test dependency management behavior.
 *
 * See test_jar_dependency_management_integration.py
 */
public class PrintClasspath {

  public static void main(String[] args) throws Exception {
    ClassLoader cl = ClassLoader.getSystemClassLoader();
    for (URL url : ((URLClassLoader)cl).getURLs()) {
      JarInputStream in = null;
      try {
        in = new JarInputStream(url.openStream());
      } catch (IOException e) {
        System.err.println("Unable to open " + url);
        continue;
      }
      Manifest mf = in.getManifest();
      String classpath = mf.getMainAttributes().getValue("Class-Path");
      in.close();

      if (classpath == null) {
        continue;
      }

      for (String entry : classpath.split(" ")) {
        System.out.println(entry);
      }
    }
  }

}
