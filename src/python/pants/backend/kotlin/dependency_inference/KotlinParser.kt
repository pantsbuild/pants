package org.pantsbuild.backend.kotlin.dependency_inference

import java.nio.file.Files
import java.nio.file.Paths
import java.nio.charset.StandardCharsets

import com.google.gson.Gson
import com.intellij.openapi.util.Disposer
import com.intellij.psi.PsiManager
import com.intellij.testFramework.LightVirtualFile
import org.jetbrains.kotlin.cli.jvm.compiler.EnvironmentConfigFiles
import org.jetbrains.kotlin.cli.jvm.compiler.KotlinCoreEnvironment
import org.jetbrains.kotlin.config.CompilerConfiguration
import org.jetbrains.kotlin.idea.KotlinFileType
import org.jetbrains.kotlin.psi.KtNamedDeclaration
import org.jetbrains.kotlin.psi.KtFile
import org.jetbrains.kotlin.psi.KtTreeVisitorVoid
import org.jetbrains.kotlin.psi.namedDeclarationRecursiveVisitor


// KtFile: https://github.com/JetBrains/kotlin/blob/8bc29a30111081ee0b0dbe06d1f648a789909a27/compiler/psi/src/org/jetbrains/kotlin/psi/KtFile.kt

data class KotlinImport(
    val name: String,
    val alias: String?,
    val isWildcard: Boolean,
)

data class KotlinAnalysis(
    val imports: List<KotlinImport>,
    val namedDeclarations: List<String>,
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

fun analyze(file: KtFile): KotlinAnalysis {
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

    return KotlinAnalysis(imports.filterNotNull(), visitor.symbols)
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
