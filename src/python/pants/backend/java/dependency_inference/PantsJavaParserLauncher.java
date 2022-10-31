package org.pantsbuild.javaparser;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jdk8.Jdk8Module;
import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.ImportDeclaration;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.NodeList;
import com.github.javaparser.ast.PackageDeclaration;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.Parameter;
import com.github.javaparser.ast.body.TypeDeclaration;
import com.github.javaparser.ast.body.VariableDeclarator;
import com.github.javaparser.ast.expr.AnnotationExpr;
import com.github.javaparser.ast.expr.Expression;
import com.github.javaparser.ast.expr.FieldAccessExpr;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.expr.Name;
import com.github.javaparser.ast.expr.NameExpr;
import com.github.javaparser.ast.nodeTypes.NodeWithType;
import com.github.javaparser.ast.type.ClassOrInterfaceType;
import com.github.javaparser.ast.type.Type;
import com.github.javaparser.ast.type.WildcardType;
import java.io.File;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Optional;
import java.util.function.Consumer;
import java.util.stream.Collectors;

class Import {
  Import(String name, boolean isStatic, boolean isAsterisk) {
    this.name = name;
    this.isStatic = isStatic;
    this.isAsterisk = isAsterisk;
  }

  public static Import fromImportDeclaration(ImportDeclaration imp) {
    return new Import(imp.getName().toString(), imp.isStatic(), imp.isAsterisk());
  }

  public final String name;
  public final boolean isStatic;
  public final boolean isAsterisk;
}

class CompilationUnitAnalysis {
  CompilationUnitAnalysis(
      Optional<String> declaredPackage,
      ArrayList<Import> imports,
      ArrayList<String> topLevelTypes,
      ArrayList<String> consumedTypes,
      ArrayList<String> exportTypes) {
    this.declaredPackage = declaredPackage;
    this.imports = imports;
    this.topLevelTypes = topLevelTypes;
    this.consumedTypes = consumedTypes;
    this.exportTypes = exportTypes;
  }

  public final Optional<String> declaredPackage;
  public final ArrayList<Import> imports;
  public final ArrayList<String> topLevelTypes;
  public final ArrayList<String> consumedTypes;
  public final ArrayList<String> exportTypes;
}

/**
 * TODO: The dependencies of this class are defined in two places: 1. `3rdparty/jvm` via import
 * inference. 2. `java_parser_artifact_requirements`. See
 * https://github.com/pantsbuild/pants/issues/13754.
 */
public class PantsJavaParserLauncher {
  // Unwrap a `Type` and return the identifiers representing the "consumed" types.
  private static List<String> unwrapIdentifiersForType(Type type) {
    if (type.isArrayType()) {
      return unwrapIdentifiersForType(type.asArrayType().getComponentType());
    } else if (type.isWildcardType()) {
      WildcardType wildcardType = type.asWildcardType();
      ArrayList<String> result = new ArrayList<>();
      if (wildcardType.getExtendedType().isPresent()) {
        result.addAll(unwrapIdentifiersForType(wildcardType.getExtendedType().get()));
      }
      if (wildcardType.getSuperType().isPresent()) {
        result.addAll(unwrapIdentifiersForType(wildcardType.getSuperType().get()));
      }
      return result;
    } else if (type.isClassOrInterfaceType()) {
      ArrayList<String> result = new ArrayList<>();
      ClassOrInterfaceType classType = type.asClassOrInterfaceType();
      Optional<NodeList<Type>> typeArguments = classType.getTypeArguments();
      if (typeArguments.isPresent()) {
        for (Type argumentType : typeArguments.get()) {
          result.addAll(unwrapIdentifiersForType(argumentType));
        }
      }
      result.add(classType.getNameWithScope());
      return result;
    } else if (type.isIntersectionType()) {
      ArrayList<String> result = new ArrayList<>();
      for (Type elementType : type.asIntersectionType().getElements()) {
        result.addAll(unwrapIdentifiersForType(elementType));
      }
      return result;
    }

    // Not handled:
    // - PrimitiveType
    // - VarType (Java `var` keyword to be inferred by the compiler.

    return new ArrayList<>();
  }

  public static void main(String[] args) throws Exception {
    String analysisOutputPath = args[0];
    String sourceToAnalyze = args[1];

    // NB: We hardcode the most permissive language level in order to capture all potential
    // sources of symbols. If certain syntax ends up deprecated in future versions, we may need to
    // allow this to be configured.
    StaticJavaParser.setConfiguration(
        new ParserConfiguration()
            .setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_17_PREVIEW));
    CompilationUnit cu = StaticJavaParser.parse(new File(sourceToAnalyze));

    // Get the source's declare package.
    Optional<String> declaredPackage =
        cu.getPackageDeclaration().map(PackageDeclaration::getName).map(Name::toString);

    // Get the source's imports.
    ArrayList<Import> imports =
        new ArrayList<Import>(
            cu.getImports().stream()
                .map(Import::fromImportDeclaration)
                .collect(Collectors.toList()));

    // Get the source's top level types
    ArrayList<String> topLevelTypes =
        new ArrayList<String>(
            cu.getTypes().stream()
                .filter(TypeDeclaration::isTopLevelType)
                .map(TypeDeclaration::getFullyQualifiedName)
                // TODO(#12293): In Java 9+ we could just flatMap(Optional::stream),
                // but we're not guaranteed Java 9+ yet.
                .filter(Optional::isPresent)
                .map(Optional::get)
                .collect(Collectors.toList()));

    HashSet<Type> candidateConsumedTypes = new HashSet<>();
    HashSet<Type> candidateExportTypes = new HashSet<>();

    Consumer<Type> consumed =
        (type) -> {
          candidateConsumedTypes.add(type);
        };
    Consumer<Type> export =
        (type) -> {
          candidateConsumedTypes.add(type);
          candidateExportTypes.add(type);
        };

    HashSet<String> consumedIdentifiers = new HashSet<>();
    HashSet<String> exportIdentifiers = new HashSet<>();

    cu.walk(
        new Consumer<Node>() {
          @Override
          public void accept(Node node) {
            if (node instanceof NodeWithType) {
              NodeWithType<?, ?> typedNode = (NodeWithType<?, ?>) node;
              consumed.accept(typedNode.getType());
            }
            if (node instanceof VariableDeclarator) {
              VariableDeclarator varDecl = (VariableDeclarator) node;
              consumed.accept(varDecl.getType());
            }
            if (node instanceof MethodDeclaration) {
              MethodDeclaration methodDecl = (MethodDeclaration) node;
              export.accept(methodDecl.getType());
              for (Parameter param : methodDecl.getParameters()) {
                export.accept(param.getType());
              }
              methodDecl.getThrownExceptions().stream().forEach(consumed);
            }
            if (node instanceof ClassOrInterfaceDeclaration) {
              ClassOrInterfaceDeclaration classOrIntfDecl = (ClassOrInterfaceDeclaration) node;
              classOrIntfDecl.getExtendedTypes().stream().forEach(export);
              classOrIntfDecl.getImplementedTypes().stream().forEach(export);
            }
            if (node instanceof AnnotationExpr) {
              AnnotationExpr annoExpr = (AnnotationExpr) node;
              consumedIdentifiers.add(annoExpr.getNameAsString());
            }
            if (node instanceof MethodCallExpr) {
              MethodCallExpr methodCallExpr = (MethodCallExpr) node;
              Optional<Expression> scopeExprOpt = methodCallExpr.getScope();
              if (scopeExprOpt.isPresent()) {
                Expression scope = scopeExprOpt.get();
                if (scope instanceof NameExpr) {
                  NameExpr nameExpr = (NameExpr) scope;
                  consumedIdentifiers.add(nameExpr.getNameAsString());
                }
              }
            }
            if (node instanceof FieldAccessExpr) {
              FieldAccessExpr fieldAccessExpr = (FieldAccessExpr) node;
              Expression scope = fieldAccessExpr.getScope();
              if (scope instanceof NameExpr) {
                NameExpr nameExpr = (NameExpr) scope;
                consumedIdentifiers.add(nameExpr.getNameAsString());
              }
            }
          }
        });

    for (Type type : candidateConsumedTypes) {
      List<String> identifiersForType = unwrapIdentifiersForType(type);
      consumedIdentifiers.addAll(identifiersForType);
      if (candidateExportTypes.contains(type)) {
        exportIdentifiers.addAll(identifiersForType);
      }
    }

    ArrayList<String> consumedTypes = new ArrayList<>(consumedIdentifiers);
    ArrayList<String> exportTypes = new ArrayList<>(exportIdentifiers);
    CompilationUnitAnalysis analysis =
        new CompilationUnitAnalysis(
            declaredPackage, imports, topLevelTypes, consumedTypes, exportTypes);
    ObjectMapper mapper = new ObjectMapper();
    mapper.registerModule(new Jdk8Module());
    mapper.writeValue(new File(analysisOutputPath), analysis);
  }
}
