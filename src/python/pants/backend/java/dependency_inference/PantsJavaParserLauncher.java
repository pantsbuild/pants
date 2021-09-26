package org.pantsbuild.javaparser;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.github.javaparser.ast.body.TypeDeclaration;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.expr.Name;
import com.github.javaparser.ast.ImportDeclaration;
import com.github.javaparser.ast.PackageDeclaration;
import com.github.javaparser.StaticJavaParser;
import java.io.File;
import java.util.AbstractCollection;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashSet;
import java.util.List;
import java.util.Optional;
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
    CompilationUnitAnalysis(String declaredPackage, ArrayList<Import> imports, ArrayList<String> topLevelTypes) {
        this.declaredPackage = declaredPackage;
        this.imports = imports;
        this.topLevelTypes = topLevelTypes;
    }

    public final String declaredPackage;
    public final ArrayList<Import> imports;
    public final ArrayList<String> topLevelTypes;
}


public class PantsJavaParserLauncher {
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

        CompilationUnitAnalysis analysis = new CompilationUnitAnalysis(declaredPackage, imports, topLevelTypes);
        ObjectMapper mapper = new ObjectMapper();
        mapper.writeValue(new File(analysisOutputPath), analysis);
    }
}
