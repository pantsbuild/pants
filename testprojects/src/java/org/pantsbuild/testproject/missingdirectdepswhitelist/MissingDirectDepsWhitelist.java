package org.pantsbuild.testproject.missingdirectdepswhitelist;

import org.pantsbuild.testproject.publish.hello.greet.Greeting;
import org.pantsbuild.testproject.missingdirectdepswhitelist2.MissingDirectDepsWhitelist2;

public class MissingDirectDepsWhitelist {
  public String doStuff() {
    MissingDirectDepsWhitelist2 scala = new MissingDirectDepsWhitelist2();
    return Greeting.greet("woop");
  }
}