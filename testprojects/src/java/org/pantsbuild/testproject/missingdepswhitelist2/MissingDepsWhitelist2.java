package org.pantsbuild.testproject.missingdepswhitelist2;

import org.pantsbuild.testproject.publish.hello.greet.Greeting;

public class MissingDepsWhitelist2 {
  public String doStuff() {
    return Greeting.greet("weep");
  }
}
