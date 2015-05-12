package org.pantsbuild.tools.jar;

import java.util.List;
import java.util.regex.Pattern;
import org.junit.Test;
import org.kohsuke.args4j.Option;
import org.pantsbuild.args4j.Parser;
import org.pantsbuild.tools.jar.Main.Options.PatternOptionHandler;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;

public class OptionsTest {

  @Test
  public void testSkipPatterns() {
    class DummyOptions {
      @Option(name = "-skip", usage = "A list of regular expressions identifying entries to skip.",
          handler = PatternOptionHandler.class)
      List<Pattern> patterns;
    }
    DummyOptions options = new DummyOptions();
    Parser.Result result = Parser.parse(options, "-skip=^foo.*$,^.*bar$");
    assertFalse(result.isFailure());
    assertEquals(2, options.patterns.size());
    assertEquals("^foo.*$", options.patterns.get(0).toString());
    assertEquals("^.*bar$", options.patterns.get(1).toString());
  }
}
