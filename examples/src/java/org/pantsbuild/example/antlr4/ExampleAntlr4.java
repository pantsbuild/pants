// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.antlr4;

import org.antlr.v4.runtime.*;
import org.pantsbuild.example.exp.ExpAntlr4Lexer;
import org.pantsbuild.example.exp.ExpAntlr4Parser;

/**
 * An example parser for mathematical expressions using Antlr version 4
 */
public class ExampleAntlr4 {

  public ExampleAntlr4() {
  }

  public Double parseExpression(String expression) throws RecognitionException  {
    ExpAntlr4Lexer lexer = new ExpAntlr4Lexer(new ANTLRInputStream(expression));
    ExpAntlr4Parser parser =  new ExpAntlr4Parser(new CommonTokenStream(lexer));
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
        System.out.println(new ExampleAntlr4().parseExpression(arg));
      } catch (RecognitionException e) {
        usage(e.toString());
      }
    }
  }
}
