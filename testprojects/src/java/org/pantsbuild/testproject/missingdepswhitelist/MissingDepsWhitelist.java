package org.pantsbuild.testproject.missingdepswhitelist;

import org.pantsbuild.testproject.publish.hello.greet.Greeting;
import org.pantsbuild.testproject.missingdepswhitelist2.MissingDepsWhitelist2;

public class MissingDepsWhitelist {
  public String doStuff() {
    MissingDepsWhitelist2 scala = new MissingDepsWhitelist2();
    return Greeting.greet("woop");
  }
}