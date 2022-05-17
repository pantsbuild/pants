package org.pantsbuild.backend.kotlin.dependency_inference

import com.google.gson.Gson
import com.intellij.openapi.util.Disposer
import com.intellij.psi.PsiManager
import com.intellij.testFramework.LightVirtualFile
import org.jetbrains.kotlin.cli.jvm.compiler.EnvironmentConfigFiles
import org.jetbrains.kotlin.cli.jvm.compiler.KotlinCoreEnvironment
import org.jetbrains.kotlin.config.CompilerConfiguration
import org.jetbrains.kotlin.idea.KotlinFileType
import org.jetbrains.kotlin.name.FqName
import org.jetbrains.kotlin.name.Name
import org.jetbrains.kotlin.psi.KtClassOrObject
import org.jetbrains.kotlin.psi.KtDotQualifiedExpression
import org.jetbrains.kotlin.psi.KtExpression
import org.jetbrains.kotlin.psi.KtFile
import org.jetbrains.kotlin.psi.KtImportList
import org.jetbrains.kotlin.psi.KtNamedDeclaration
import org.jetbrains.kotlin.psi.KtPackageDirective
import org.jetbrains.kotlin.psi.KtSimpleNameExpression
import org.jetbrains.kotlin.psi.KtTreeVisitorVoid
import java.nio.charset.StandardCharsets
import java.nio.file.Files
import java.nio.file.Paths

// KtFile: https://github.com/JetBrains/kotlin/blob/8bc29a30111081ee0b0dbe06d1f648a789909a27/compiler/psi/src/org/jetbrains/kotlin/psi/KtFile.kt

data class KotlinImport(
    val name: String,
    val alias: String?,
    val isWildcard: Boolean,
)

data class KotlinAnalysis(
    val `package`: String,
    val imports: List<KotlinImport>,
    val namedDeclarations: List<String>,
    val scopes: List<String>,
    val consumedSymbolsByScope: Map<String, List<String>>
)

fun parse(code: String): KtFile {
    val disposable = Disposer.newDisposable()
    try {
        val env = KotlinCoreEnvironment.createForProduction(
            disposable, CompilerConfiguration(), EnvironmentConfigFiles.JVM_CONFIG_FILES)
        val file = LightVirtualFile("temp.kt", KotlinFileType.INSTANCE, code)
        return PsiManager.getInstance(env.project).findFile(file) as KtFile
    } finally {
        disposable.dispose()
    }
}

fun nameFromExpression(expression: KtExpression?): Name? {
    if (expression == null) {
        return null
    }
    return when (expression) {
        is KtSimpleNameExpression -> expression.getReferencedNameAsName()
        else -> null
    }
}

fun fqNameFromExpression(expression: KtExpression?): FqName? {
    if (expression == null) {
        return null
    }

    return when (expression) {
        is KtDotQualifiedExpression -> {
            val dotQualifiedExpression = expression as KtDotQualifiedExpression
            val parentFqn: FqName? = fqNameFromExpression(dotQualifiedExpression.receiverExpression)
            val child: Name = nameFromExpression(dotQualifiedExpression.selectorExpression) ?: return parentFqn
            if (parentFqn != null) {
                parentFqn.child(child)
            } else null
        }
        is KtSimpleNameExpression -> FqName.topLevel(expression.getReferencedNameAsName())
        else -> null
    }
}
fun analyze(file: KtFile): KotlinAnalysis {
    val pkg = file.packageFqName.asString()

    val imports = file.importDirectives.map { importDirective ->
        val name = importDirective.importedFqName
        if (name != null) {
            KotlinImport(
                name=name.asString(),
                alias=importDirective.aliasName,
                isWildcard=importDirective.isAllUnder,
            )
        } else {
            null
        }
    }
    val visitor = object : KtTreeVisitorVoid() {
        val symbols = ArrayList<String>()
        override fun visitNamedDeclaration(decl: KtNamedDeclaration) {
            val fqName = decl.getFqName()
            if (fqName != null) {
                symbols.add(fqName.asString())
            }
        }
    }
    visitor.visitKtFile(file, null)

    val consumedSymbolsVisitor = object : KtTreeVisitorVoid() {
        val symbolsByScope = mutableMapOf<String, MutableSet<String>>()
        val scopes = mutableSetOf<String>(pkg)
        var currentScope = pkg

        override fun visitClassOrObject(classOrObject: KtClassOrObject) {
            val oldScope = currentScope
            val classId = classOrObject.getClassId()
            if (classId != null && !classId.isLocal) {
                currentScope = classId.asFqNameString()
                scopes.add(currentScope)
            }
            super.visitClassOrObject(classOrObject)
            currentScope = oldScope
        }

        // Skip recursing for imports directives and the package directive so they do not show up
        // in the consumed symbols analysis.
        override fun visitImportList(importList: KtImportList) {}
        override fun visitPackageDirective(directive: KtPackageDirective) {}

        override fun visitDotQualifiedExpression(expr: KtDotQualifiedExpression) {
            val fqName = fqNameFromExpression(expr)
            if (fqName != null) {
                if (!symbolsByScope.contains(currentScope)) {
                    symbolsByScope.put(currentScope, mutableSetOf<String>())
                }
                val symbolsForScope = symbolsByScope.get(currentScope)
                symbolsForScope?.add(fqName.asString())
            }
        }

        override fun visitSimpleNameExpression(expr: KtSimpleNameExpression) {
            val fqName = fqNameFromExpression(expr)
            if (fqName != null) {
                if (!symbolsByScope.contains(currentScope)) {
                    symbolsByScope.put(currentScope, mutableSetOf<String>())
                }
                val symbolsForScope = symbolsByScope.get(currentScope)
                symbolsForScope?.add(fqName.asString())
            }
        }
    }
    consumedSymbolsVisitor.visitKtFile(file)

    return KotlinAnalysis(
        pkg,
        imports.filterNotNull(),
        visitor.symbols,
        consumedSymbolsVisitor.scopes.toList(),
        consumedSymbolsVisitor.symbolsByScope.mapValues { it.value.toList() },
    )
}

fun main(args: Array<String>) {
    val analysisOutputPath = args[0]
    val sourcePath = args[1]

    val sourceContentBytes = Files.readAllBytes(Paths.get(sourcePath))
    val sourceContent = String(sourceContentBytes, StandardCharsets.UTF_8)
    val parsed = parse(sourceContent)
    val analysis = analyze(parsed)

    val gson = Gson()
    val analysisOutput = gson.toJson(analysis)
    Files.write(Paths.get(analysisOutputPath), analysisOutput.toByteArray(StandardCharsets.UTF_8))
}
