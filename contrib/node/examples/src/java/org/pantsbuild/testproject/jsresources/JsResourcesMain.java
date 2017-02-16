package org.pantsbuild.testproject.jsresources;

import com.google.common.base.Charsets;
import com.google.common.io.Resources;
import java.io.IOException;
import java.net.URL;

public class JsResourcesMain {
  private static String RESOURCE_PATH = "web-component-button-processed/Button.js";
  private static String ALT_RESOURCE_PATH = (
    "web-component-button-processed-with-dependency-artifacts/Button.js");

  public static void main(String[] args) throws IOException {
    // Introduce a 3rdparty library so we can test if Manifest's Class-Path entry is
    // set properly for both internal and external dependencies.
    URL resourceUrl;
    try {
      resourceUrl = Resources.getResource(RESOURCE_PATH);
    } catch (IllegalArgumentException e) {
      resourceUrl = Resources.getResource(ALT_RESOURCE_PATH);
    }
    String content = Resources.toString(resourceUrl, Charsets.UTF_8);
    // Ensure resource is loaded properly.
    System.out.println(content);
  }

  private JsResourcesMain() {
    // not called. placates checkstyle
  }
}
