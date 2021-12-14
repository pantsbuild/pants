/**
 * TODO: The dependencies of this class are defined in two places:
 *   1. `3rdparty/jvm` via import inference.
 *   2. `SCALA_PARSER_ARTIFACT_REQUIREMENTS`.
 * See https://github.com/pantsbuild/pants/issues/13754.
 */
package org.pantsbuild.backend.scala.dependency_inference

import io.circe._
import io.circe.generic.auto._
import io.circe.syntax._

import scala.meta._
import scala.meta.transversers.Traverser

import scala.collection.mutable.{ArrayBuffer, HashMap, HashSet}
import scala.reflect.NameTransformer

case class AnImport(
   // The partially qualified input name for the import, which must be in scope at
   // the import site.
   name: String,
   // An optional single token alias for the import in this scope.
   alias: Option[String],
   // True if the import imports all symbols contained within the name.
   isWildcard: Boolean,
)

case class Analysis(
   providedSymbols: Vector[String],
   providedSymbolsEncoded: Vector[String],
   importsByScope: HashMap[String, ArrayBuffer[AnImport]],
   consumedSymbolsByScope: HashMap[String, HashSet[String]],
   scopes: Vector[String],
)

case class ProvidedSymbol(sawClass: Boolean, sawTrait: Boolean, sawObject: Boolean)

class SourceAnalysisTraverser extends Traverser {
  val nameParts = ArrayBuffer[String]()
  var skipProvidedNames = false

  val providedSymbolsByScope = HashMap[String, HashMap[String, ProvidedSymbol]]()
  val importsByScope = HashMap[String, ArrayBuffer[AnImport]]()
  val consumedSymbolsByScope = HashMap[String, HashSet[String]]()
  val scopes = HashSet[String]()

  // Extract a qualified name from a tree.
  def extractName(tree: Tree): String = {
    tree match {
      case Term.Select(qual, name) => s"${extractName(qual)}.${extractName(name)}"
      case Type.Select(qual, name) => s"${extractName(qual)}.${extractName(name)}"
      case Term.Name(name) => name
      case Type.Name(name) => name
      case Pat.Var(node) => extractName(node)
      case Name.Indeterminate(name) => name
      case _ => ""
    }
  }

  def extractNamesFromTypeTree(tree: Tree): Vector[String] = {
    tree match {
      case Type.Name(name) => Vector(name)
      case Type.Select(qual, Type.Name(name)) => {
        val qualName = extractName(qual)
        Vector(s"${qualName}.${name}")
      }
      case Type.Apply(tpe, args) => extractNamesFromTypeTree(tpe) ++ args.toVector.flatMap(extractNamesFromTypeTree(_))
      case Type.ApplyInfix(lhs, _op, rhs) => extractNamesFromTypeTree(lhs) ++ extractNamesFromTypeTree(rhs)
      case Type.Function(params, res) =>
        params.toVector.flatMap(extractNamesFromTypeTree(_)) ++ extractNamesFromTypeTree(res)
      case Type.PolyFunction(_tparams, tpe) => extractNamesFromTypeTree(tpe)
      case Type.ContextFunction(params, res) =>
        params.toVector.flatMap(extractNamesFromTypeTree(_)) ++ extractNamesFromTypeTree(res)
      case Type.Tuple(args) => args.toVector.flatMap(extractNamesFromTypeTree(_))
      case Type.With(lhs, rhs) => extractNamesFromTypeTree(lhs) ++ extractNamesFromTypeTree(rhs)
      case Type.And(lhs, rhs) => extractNamesFromTypeTree(lhs) ++ extractNamesFromTypeTree(rhs)
      case Type.Or(lhs, rhs) => extractNamesFromTypeTree(lhs) ++ extractNamesFromTypeTree(rhs)
      // TODO: Recurse into `_stats` to find additional types.
      // A `Type.Refine` represents syntax: A { def f: Int }
      case Type.Refine(typeOpt, _stats) => typeOpt.toVector.flatMap(extractNamesFromTypeTree(_))
      case Type.Existential(tpe, _stats) => extractNamesFromTypeTree(tpe)
      case Type.Annotate(tpe, _annots) => extractNamesFromTypeTree(tpe)
      case Type.Lambda(_tparams, tpe) => extractNamesFromTypeTree(tpe)
      case Type.Bounds(loOpt, hiOpt) =>
        loOpt.toVector.flatMap(extractNamesFromTypeTree(_)) ++ hiOpt.toVector.flatMap(extractNamesFromTypeTree(_))
      case Type.ByName(tpe) => extractNamesFromTypeTree(tpe)
      case Type.Repeated(tpe) => extractNamesFromTypeTree(tpe)
      // TODO: Should we extract a type from _tpe?
      // `Type.Match` represents this Scala 3 syntax: type T = match { case A => B }
      case Type.Match(_tpe, cases) => cases.toVector.flatMap(extractNamesFromTypeTree(_))
      case TypeCase(pat, body) => extractNamesFromTypeTree(pat) ++ extractNamesFromTypeTree(body)
      case _ => Vector()
    }
  }

  def recordProvidedName(symbolName: String, sawClass: Boolean = false, sawTrait: Boolean = false, sawObject: Boolean = false): Unit = {
    if (!skipProvidedNames) {
      val fullPackageName = nameParts.mkString(".")
      if (!providedSymbolsByScope.contains(fullPackageName)) {
        providedSymbolsByScope(fullPackageName) = HashMap[String, ProvidedSymbol]()
      }
      val providedSymbols = providedSymbolsByScope(fullPackageName)

      if (providedSymbols.contains(symbolName)) {
        val existingSymbol = providedSymbols(symbolName)
        val newSymbol = ProvidedSymbol(
          sawClass = existingSymbol.sawClass || sawClass,
          sawTrait = existingSymbol.sawTrait || sawTrait,
          sawObject = existingSymbol.sawObject || sawObject,
        )
        providedSymbols(symbolName) = newSymbol
      } else {
        providedSymbols(symbolName) = ProvidedSymbol(
          sawClass = sawClass,
          sawTrait = sawTrait,
          sawObject = sawObject
        )
      }
    }
  }

  def withNamePart[T](namePart: String, f: () => T): T = {
    nameParts.append(namePart)
    val result = f()
    nameParts.remove(nameParts.length - 1)
    result
  }

  def withSuppressProvidedNames[T](f: () => T): Unit = {
    val origSkipProvidedNames = skipProvidedNames
    skipProvidedNames = true
    f()
    skipProvidedNames = origSkipProvidedNames
  }

  def recordImport(name: String, alias: Option[String], isWildcard: Boolean): Unit = {
    val fullPackageName = nameParts.mkString(".")
    if (!importsByScope.contains(fullPackageName)) {
      importsByScope(fullPackageName) = ArrayBuffer[AnImport]()
    }
    importsByScope(fullPackageName).append(AnImport(name, alias, isWildcard))
  }

  def recordConsumedSymbol(name: String): Unit = {
    val fullPackageName = nameParts.mkString(".")
    if (!consumedSymbolsByScope.contains(fullPackageName)) {
      consumedSymbolsByScope(fullPackageName) = HashSet[String]()
    }
    consumedSymbolsByScope(fullPackageName).add(name)
  }

  def recordScope(name: String): Unit = {
    val scopeName = (nameParts.toVector ++ Vector(name)).mkString(".")
    scopes.add(scopeName)
  }

  def visitTemplate(templ: Template, name: String): Unit = {
    templ.inits.foreach(init => apply(init))
    withNamePart(name, () => {
      apply(templ.early)
      apply(templ.stats)
    })
  }

  def visitMods(mods: List[Mod]): Unit = {
    mods.foreach({
      case Mod.Annot(init) => apply(init)  // rely on `Init` extraction in main parsing match code
      case _ => ()
    })
  }

  override def apply(tree: Tree): Unit = tree match {
    case Pkg(ref, stats) => {
      val name = extractName(ref)
      recordScope(name)
      withNamePart(name, () => super.apply(stats))
    }

    case Pkg.Object(mods, nameNode, templ) => {
      visitMods(mods)
      val name = extractName(nameNode)
      recordScope(name)
      visitTemplate(templ, name)
    }

    case Defn.Class(mods, nameNode, _tparams, _ctor, templ) => {
      visitMods(mods)
      val name = extractName(nameNode)
      recordProvidedName(name, sawClass = true)
      visitTemplate(templ, name)
    }

    case Defn.Trait(mods, nameNode, _tparams, _ctor, templ) => {
      visitMods(mods)
      val name = extractName(nameNode)
      recordProvidedName(name, sawTrait = true)
      visitTemplate(templ, name)
    }

    case Defn.Object(mods, nameNode, templ) => {
      visitMods(mods)
      val name = extractName(nameNode)
      recordProvidedName(name, sawObject = true)
      visitTemplate(templ, name)
    }

    case Defn.Type(mods, nameNode, _tparams, _body) => {
      visitMods(mods)
      val name = extractName(nameNode)
      recordProvidedName(name)
    }

    case Defn.Val(mods, pats, decltpe, rhs) => {
      visitMods(mods)
      pats.headOption.foreach(pat => {
        val name = extractName(pat)
        recordProvidedName(name)
      })
      decltpe.foreach(tpe => {
        recordConsumedSymbol(extractName(tpe))
      })
      super.apply(rhs)
    }

    case Defn.Var(mods, pats, decltpe, rhs) => {
      visitMods(mods)
      pats.headOption.foreach(pat => {
        val name = extractName(pat)
        recordProvidedName(name)
      })
      decltpe.foreach(tpe => {
        extractNamesFromTypeTree(tpe).foreach(recordConsumedSymbol(_))
      })
      super.apply(rhs)
    }

    case Defn.Def(mods, nameNode, _tparams, params, decltpe, body) => {
      visitMods(mods)
      val name = extractName(nameNode)
      recordProvidedName(name)

      decltpe.foreach(tpe => {
        extractNamesFromTypeTree(tpe).foreach(recordConsumedSymbol(_))
      })

      params.foreach(param => apply(param))

      withSuppressProvidedNames(() => apply(body))
    }

    case Import(importers) => {
      importers.foreach({ case Importer(ref, importees) =>
        val baseName = extractName(ref)
        importees.foreach(importee => {
          importee match {
            case Importee.Wildcard() => recordImport(baseName, None, true)
            case Importee.Name(nameNode) => {
              recordImport(s"${baseName}.${extractName(nameNode)}", None, false)
            }
            case Importee.Rename(nameNode, aliasNode) => {
              // If a type is aliased to `_`, it is not brought into scope. We still record
              // the import though, since compilation will fail if an import is not present.
              val alias = extractName(aliasNode)
              recordImport(
                s"${baseName}.${extractName(nameNode)}",
                if (alias == "_") None else Some(alias),
                false,
              )
            }
            case _ =>
          }
        })
      })
    }

    case Init(tpe, _name, _argss) => {
      extractNamesFromTypeTree(tpe).foreach(recordConsumedSymbol(_))
    }

    case Term.Param(mods, _name, decltpe, _default) => {
      visitMods(mods)
      decltpe.foreach(tpe => {
        extractNamesFromTypeTree(tpe).foreach(recordConsumedSymbol(_))
      })
    }

    case Ctor.Primary(mods, _name, params_list) => {
      visitMods(mods)
      params_list.foreach(params => {
        params.foreach(param => apply(param))
      })
    }

    case Ctor.Secondary(mods, _name, params_list, init, stats) => {
      visitMods(mods)
      params_list.foreach(params => {
        params.foreach(param => apply(param))
      })
      init.argss.foreach(arg => apply(arg))
    }

    case node @ Term.Select(_, _) => {
      val name = extractName(node)
      recordConsumedSymbol(name)
    }

    case node @ Term.Name(_) => {
      val name = extractName(node)
      recordConsumedSymbol(name)
    }

    case node => super.apply(node)
  }

  def gatherProvidedSymbols(): Vector[String] = {
    providedSymbolsByScope.flatMap({ case (scopeName, symbolsForScope) =>
      symbolsForScope.keys.map(symbolName => s"${scopeName}.${symbolName}").toVector
    }).toVector
  }

  def gatherEncodedProvidedSymbols(): Vector[String] = {
    providedSymbolsByScope.flatMap({ case (scopeName, symbolsForScope) =>
      val encodedSymbolsForScope = symbolsForScope.flatMap({ case (symbolName, symbol) => {
        val encodedSymbolName = NameTransformer.encode(symbolName)
        val result = ArrayBuffer[String](encodedSymbolName)
        if (symbol.sawObject) {
          result.append(encodedSymbolName + "$")
          result.append(encodedSymbolName + "$.MODULE$")
        }
        result.toVector
      }})

      encodedSymbolsForScope.map(symbolName => s"${scopeName}.${symbolName}")
    }).toVector
  }

  def toAnalysis: Analysis = {
    Analysis(
      providedSymbols = gatherProvidedSymbols(),
      providedSymbolsEncoded = gatherEncodedProvidedSymbols(),
      importsByScope = importsByScope,
      consumedSymbolsByScope = consumedSymbolsByScope,
      scopes = scopes.toVector,
    )
  }
}

object ScalaParser {
  def analyze(pathStr: String): Analysis = {
    val path = java.nio.file.Paths.get(pathStr)
    val bytes = java.nio.file.Files.readAllBytes(path)
    val text = new String(bytes, "UTF-8")
    val input = Input.VirtualFile(path.toString, text)

    val tree = input.parse[Source].get

    val analysisTraverser = new SourceAnalysisTraverser()
    analysisTraverser.apply(tree)
    analysisTraverser.toAnalysis
  }

  def main(args: Array[String]): Unit = {
    val outputPath = java.nio.file.Paths.get(args(0))
    val analysis = analyze(args(1))

    val json = analysis.asJson.noSpaces
    java.nio.file.Files.write(outputPath, json.getBytes(),
      java.nio.file.StandardOpenOption.CREATE_NEW, java.nio.file.StandardOpenOption.WRITE)
  }
}
