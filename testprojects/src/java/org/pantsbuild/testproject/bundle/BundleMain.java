package org.pantsbuild.testproject.bundle;

import com.google.common.base.Charsets;
import com.google.common.io.Resources;
import java.io.IOException;

public class BundleMain {
  private static String RESOURCE_PATH = "org/pantsbuild/testproject/bundleresources/resources.txt";

  public static void main(String[] args) throws IOException {
    // Introduce a 3rdparty library so we can test if Manifest's Class-Path entry is
    // set properly for both internal and external dependencies.
    String content = Resources.toString(Resources.getResource(RESOURCE_PATH), Charsets.UTF_8);
    // Ensure resource is loaded properly.
    System.out.println("Hello world from " + content);
  }

  private BundleMain() {
    // not called. placates checkstyle
  }
}
