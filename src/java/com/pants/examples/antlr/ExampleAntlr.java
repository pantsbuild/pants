package com.pants.examples.antlr;

import java.io.IOException;
import com.pants.examples.json.JsonLexer;
import com.pants.examples.json.JsonParser;

class ExampleAntlr {

  private ExampleAntlr() {
  }

  public static void main(String[] args) {
    InputStream sin = null;
    try {
      sin = ExampleAntlr.class.getResourceAsStream("vectornd.js");
    } catch (IOException e) {
      // what's the policy here?
    }

    JsonLexer lexer = new JsonLexer(sin);
    JsonParser parser = new JsonParser(lexer);
    parser.object();
  }
}