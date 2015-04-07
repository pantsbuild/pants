package org.pantsbuild.testproject.missingdirectdepswhitelist2;

import org.pantsbuild.testproject.publish.hello.greet.Greeting;

public class MissingDirectDepsWhitelist2 {
  public String doStuff() {
    return Greeting.greet("weep");
  }
}