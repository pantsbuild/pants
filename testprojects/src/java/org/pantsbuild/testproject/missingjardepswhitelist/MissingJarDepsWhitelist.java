package org.pantsbuild.testproject.missingjardepswhitelist;

import org.pantsbuild.testproject.missingjardepswhitelist2.MissingJarDepsWhitelist2;
import com.google.common.io.Closer;

public class MissingJarDepsWhitelist {
  public String meow() {
    Closer c = Closer.create();
    MissingJarDepsWhitelist2 m = new MissingJarDepsWhitelist2();
    return m.meow() + '!';
  }
}
