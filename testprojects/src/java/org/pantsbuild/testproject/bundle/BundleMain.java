package org.pantsbuild.testproject.bundle;

import com.google.common.base.Joiner;
import com.google.common.base.Splitter;
import java.io.IOException;

public class BundleMain {

  public static void main(String[] args) throws IOException {
    // The sole purpose is to introduce a 3rdparty library so we can test if
    // Manifest's Class-Path entry is set properly for both internal and
    // external dependencies.
    System.out.println(Joiner.on(", ").join(Splitter.on(", ").split("Hello, world.")));
  }

  private BundleMain() {
    // not called. placates checkstyle
  }
}
