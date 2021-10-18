package org.pantsbuild.javaparser;

import com.fasterxml.jackson.databind.ObjectMapper;
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
import com.github.javaparser.ast.expr.Name;
import com.github.javaparser.ast.nodeTypes.NodeWithType;
import com.github.javaparser.ast.type.ClassOrInterfaceType;
import com.github.javaparser.ast.type.Type;
import com.github.javaparser.ast.type.WildcardType;

import java.io.File;
import java.util.AbstractCollection;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashSet;
import java.util.List;
import java.util.Optional;
import java.util.function.Consumer;
import java.util.stream.Collectors;
import java.util.stream.Stream;

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
        String declaredPackage,
        ArrayList<Import> imports,
        ArrayList<String> topLevelTypes,
        ArrayList<String> consumedUnqualifiedTypes
    ) {
        this.declaredPackage = declaredPackage;
        this.imports = imports;
        this.topLevelTypes = topLevelTypes;
        this.consumedUnqualifiedTypes = consumedUnqualifiedTypes;
    }

    public final String declaredPackage;
    public final ArrayList<Import> imports;
    public final ArrayList<String> topLevelTypes;
    public final ArrayList<String> consumedUnqualifiedTypes;
}


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

        CompilationUnit cu = StaticJavaParser.parse(new File(sourceToAnalyze));

        // Get the source's declare package.
        String declaredPackage = cu.getPackageDeclaration()
            .map(PackageDeclaration::getName)
            .map(Name::toString)
            .orElse("");

        // Get the source's imports.
        ArrayList<Import> imports = new ArrayList<Import>(
            cu.getImports().stream()
                .map(Import::fromImportDeclaration)
                .collect(Collectors.toList()));

        // Get the source's top level types
        ArrayList<String> topLevelTypes = new ArrayList<String>(
            cu.getTypes().stream()
                .filter(TypeDeclaration::isTopLevelType)
                .map(TypeDeclaration::getFullyQualifiedName)
                // TODO(#12293): In Java 9+ we could just flatMap(Optional::stream),
                // but we're not guaranteed Java 9+ yet.
                .filter(Optional::isPresent)
                .map(Optional::get)
                .collect(Collectors.toList()));

        HashSet<Type> candidateConsumedTypes = new HashSet<>();
        cu.walk(new Consumer<Node>() {
            @Override
            public void accept(Node node) {
                if (node instanceof NodeWithType) {
                    NodeWithType<?, ?> typedNode = (NodeWithType<?, ?>) node;
                    candidateConsumedTypes.add(typedNode.getType());
                }
                if (node instanceof VariableDeclarator) {
                    VariableDeclarator varDecl = (VariableDeclarator) node;
                    candidateConsumedTypes.add(varDecl.getType());
                }
                if (node instanceof MethodDeclaration) {
                    MethodDeclaration methodDecl = (MethodDeclaration) node;
                    candidateConsumedTypes.add(methodDecl.getType());
                    for (Parameter param : methodDecl.getParameters()) {
                        candidateConsumedTypes.add(param.getType());
                    }
                    System.out.println("Method type: " + methodDecl.getType());
                }
                if (node instanceof ClassOrInterfaceDeclaration) {
                    ClassOrInterfaceDeclaration classOrIntfDecl = (ClassOrInterfaceDeclaration) node;
                    candidateConsumedTypes.addAll(classOrIntfDecl.getExtendedTypes());
                    candidateConsumedTypes.addAll(classOrIntfDecl.getImplementedTypes());
                }
            }
        });

        HashSet<String> identifiers = new HashSet<>();
        for (Type type : candidateConsumedTypes) {
            List<String> identifiersForType = unwrapIdentifiersForType(type);
            identifiers.addAll(identifiersForType);
        }

        ArrayList<String> consumedUnqualifiedTypes = new ArrayList<>(identifiers);

        CompilationUnitAnalysis analysis = new CompilationUnitAnalysis(declaredPackage, imports, topLevelTypes, consumedUnqualifiedTypes);
        ObjectMapper mapper = new ObjectMapper();
        mapper.writeValue(new File(analysisOutputPath), analysis);
    }
}
