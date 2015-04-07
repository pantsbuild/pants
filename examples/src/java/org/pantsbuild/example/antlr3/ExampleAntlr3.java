// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.antlr3;

import org.antlr.runtime.*;
import org.pantsbuild.example.exp.ExpAntlr3Lexer;
import org.pantsbuild.example.exp.ExpAntlr3Parser;

/**
 * An example for parsing mathematical expressions using Antlr version 3
 */
public class ExampleAntlr3 {

  public ExampleAntlr3() {
  }

  public Double parseExpression(String expression) throws RecognitionException  {
    ExpAntlr3Lexer lexer = new ExpAntlr3Lexer(new ANTLRStringStream(expression));
    ExpAntlr3Parser parser =  new ExpAntlr3Parser(new CommonTokenStream(lexer));
    return parser.eval().value;
  }

  public static void usage(String message) {
    System.err.println(message);
    System.err.println("usage: \"expression\" [ \"expresion\" [ ... ] ]");
    System.err.println("  Specify a mathematical expression using +, -, *, / and (");
    System.exit(1);
  }

  public static void main(String[] args) {
    if (args.length == 0) {
      usage("No expression specified.");
    }
    for (String arg : args) {
      try {
        System.out.println(new ExampleAntlr3().parseExpression(arg));
      } catch (RecognitionException e) {
        usage(e.toString());
      }
    }
  }
}
