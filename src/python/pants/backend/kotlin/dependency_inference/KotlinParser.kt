package org.pantsbuild.backend.kotlin.dependency_inference

import kotlinx.serialization.*
import kotlinx.serialization.json.*

import com.intellij.openapi.util.Disposer
import com.intellij.psi.PsiManager
import com.intellij.testFramework.LightVirtualFile
import org.jetbrains.kotlin.cli.jvm.compiler.EnvironmentConfigFiles
import org.jetbrains.kotlin.cli.jvm.compiler.KotlinCoreEnvironment
import org.jetbrains.kotlin.config.CompilerConfiguration
import org.jetbrains.kotlin.idea.KotlinFileType
import org.jetbrains.kotlin.psi.KtFile

import java.io.File
import java.io.FileWriter

// KtFile: https://github.com/JetBrains/kotlin/blob/master/compiler/psi/src/org/jetbrains/kotlin/psi/KtFile.kt

@Serializable
data class KotlinImport(
    val name: String,
    val alias: String?,
    val isWildcard: Boolean,
)

@Serializable
data class KotlinAnalysis(
    val imports: List<KotlinImport>,
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
      val name = importDirective.getName()
      KotlinImport(
        name=importDirective.getName() ?: "",
        alias=null,
        isWildcard=false,
      )
    }

    return KotlinAnalysis(imports)
}

fun main(args: Array<String>) {
    val analysisOutputPath = args[0]
    val sourceToAnalyze = args[1]

    val parsed = parse(sourceToAnalyze)
    val analysis = analyze(parsed)

    val outputFile = File(analysisOutputPath)
        val writer = FileWriter(outputFile)
    try {
        val analysisOutput = Json.encodeToString(analysis)
        writer.write(analysisOutput)
    } finally {
        writer.close()
    }
}
