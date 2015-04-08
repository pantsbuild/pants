package org.pantsbuild.example.useantlr;

import org.pantsbuild.example.antlr3.ExampleAntlr3;
import org.junit.*;

import static org.junit.Assert.assertEquals;

public class Antlr3Test {

  @Test
  public void testExpression() throws Exception {
    ExampleAntlr3 parser = new ExampleAntlr3();
    assertEquals(48.0, parser.parseExpression("8 * 6"), .001);
    assertEquals(24.0, parser.parseExpression("2 * 3 * (2 + 2)"), .001);
  }
}
