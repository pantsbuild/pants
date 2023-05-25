// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
const parser = require("@babel/parser");
const traverse = require("@babel/traverse").default;
const fs = require("fs").promises;

const PRAGMA_IGNORE = "pants: no-infer-dep";

const printStringArguments = (callPath) => {
  for (const arg of callPath.node.arguments) {
    if (arg.type === "StringLiteral") {
      console.log(arg.value);
    }
  }
};

const ignorePath = (pragmaIgnoredLines, path) =>
  pragmaIgnoredLines.has(path.node.loc.start.line);

const functionImportsVisitor = (pragmaIgnoredLines) => {
  return {
    CallExpression: (callPath) => {
      if (ignorePath(pragmaIgnoredLines, callPath)) {
        return;
      }
      callPath.traverse({
        Identifier: (identPath) => {
          if (identPath.node.name === "require") {
            printStringArguments(callPath);
          }
        },
        Import: () => printStringArguments(callPath),
      });
    },
  };
};

const staticImportVisitor = (pragmaIgnoredLines) => {
  return {
    ImportDeclaration: (importPath) => {
      if (ignorePath(pragmaIgnoredLines, importPath)) {
        return;
      }
      importPath.traverse({
        StringLiteral: (literalPath) => console.log(literalPath.node.value),
      });
    },
  };
};

const getPragmaIgnoredLines = (ast) => {
  if (Array.isArray(ast.comments)) {
    return new Set(
      ast.comments
        .filter((comment) => {
          return (
            comment.type === "CommentLine" &&
            comment.value.includes(PRAGMA_IGNORE)
          );
        })
        .map((commentLine) => commentLine.loc.start.line)
    );
  }
  return new Set();
};

const main = async () => {
  const [file] = process.argv.slice(2);

  const code = await fs.readFile(file, "utf-8");

  const ast = parser.parse(code, {
    sourceType: "unambiguous",
    errorRecovery: true,
  });
  const pragmaIgnoredLines = getPragmaIgnoredLines(ast);

  traverse(ast, {
    Program: (programPath) =>
      console.error(`Determined SourceType: ${programPath.node.sourceType}.`),
    ...functionImportsVisitor(pragmaIgnoredLines),
    ...staticImportVisitor(pragmaIgnoredLines),
  });
};

(async () => {
  try {
    await main();
  } catch (e) {
    console.error(e);
    process.exit(1);
  }
})();
