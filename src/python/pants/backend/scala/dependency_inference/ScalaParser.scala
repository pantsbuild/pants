/** TODO: The dependencies of this class are defined in two places:
  *   1. `3rdparty/jvm` via import inference. 2. `SCALA_PARSER_ARTIFACT_REQUIREMENTS`. See
  *      https://github.com/pantsbuild/pants/issues/13754.
  */
package org.pantsbuild.backend.scala.dependency_inference

import io.circe._
import io.circe.generic.auto._
import io.circe.syntax._

import scala.meta._
import scala.meta.transversers.Traverser

import scala.collection.SortedSet
import scala.collection.mutable.{ArrayBuffer, HashMap, HashSet}
import scala.reflect.NameTransformer

case class AnImport(
    // The partially qualified input name for the import, which must be in scope at
    // the import site.
    name: String,
    // An optional single token alias for the import in this scope.
    alias: Option[String],
    // True if the import imports all symbols contained within the name.
    isWildcard: Boolean
)

case class Analysis(
    providedSymbols: SortedSet[Analysis.ProvidedSymbol],
    providedSymbolsEncoded: SortedSet[Analysis.ProvidedSymbol],
    importsByScope: HashMap[String, ArrayBuffer[AnImport]],
    consumedSymbolsByScope: HashMap[String, HashSet[String]],
    scopes: Vector[String]
)
object Analysis {
  case class ProvidedSymbol(name: String, recursive: Boolean)
  implicit val providedSymbolOrdering: Ordering[ProvidedSymbol] = Ordering.by(_.name)
}

case class ProvidedSymbol(
    sawClass: Boolean,
    sawTrait: Boolean,
    sawObject: Boolean,
    recursive: Boolean
)

class SourceAnalysisTraverser extends Traverser {
  val nameParts = ArrayBuffer[String]()
  var skipProvidedNames = false

  val providedSymbolsByScope = HashMap[String, HashMap[String, ProvidedSymbol]]()
  val importsByScope = HashMap[String, ArrayBuffer[AnImport]]()
  val consumedSymbolsByScope = HashMap[String, HashSet[String]]()
  val scopes = HashSet[String]()

  // Extract a qualified name from a tree.
  def extractName(tree: Tree): String = {
    def extractNameSelect(qual: Tree, name: Tree): Option[String] =
      (maybeExtractName(qual), maybeExtractName(name)) match {
        case (Some(qual), Some(name)) => Some(s"$qual.$name")
        case (Some(qual), None)       => Some(qual)
        case (None, Some(name))       => Some(name)
        case (None, None)             => None
      }

    def maybeExtractName(tree: Tree): Option[String] =
      tree match {
        case Term.Select(qual, name)  => extractNameSelect(qual, name)
        case Type.Select(qual, name)  => extractNameSelect(qual, name)
        case Term.Name(name)          => Some(name)
        case Type.Name(name)          => Some(name)
        case Pat.Var(node)            => maybeExtractName(node)
        case Name.Indeterminate(name) => Some(name)
        case _                        => None
      }

    maybeExtractName(tree).getOrElse("")
  }

  def extractNamesFromTypeTree(tree: Tree): Vector[String] = {
    tree match {
      case Type.Name(name) => Vector(name)
      case Type.Select(qual, Type.Name(name)) => {
        val qualName = extractName(qual)
        Vector(qualifyName(qualName, name))
      }
      case Type.Apply(tpe, args) =>
        extractNamesFromTypeTree(tpe) ++ args.toVector.flatMap(extractNamesFromTypeTree(_))
      case Type.ApplyInfix(lhs, _op, rhs) =>
        extractNamesFromTypeTree(lhs) ++ extractNamesFromTypeTree(rhs)
      case Type.Function(params, res) =>
        params.toVector.flatMap(extractNamesFromTypeTree(_)) ++ extractNamesFromTypeTree(res)
      case Type.PolyFunction(_tparams, tpe) => extractNamesFromTypeTree(tpe)
      case Type.ContextFunction(params, res) =>
        params.toVector.flatMap(extractNamesFromTypeTree(_)) ++ extractNamesFromTypeTree(res)
      case Type.Tuple(args)    => args.toVector.flatMap(extractNamesFromTypeTree(_))
      case Type.With(lhs, rhs) => extractNamesFromTypeTree(lhs) ++ extractNamesFromTypeTree(rhs)
      case Type.And(lhs, rhs)  => extractNamesFromTypeTree(lhs) ++ extractNamesFromTypeTree(rhs)
      case Type.Or(lhs, rhs)   => extractNamesFromTypeTree(lhs) ++ extractNamesFromTypeTree(rhs)
      // TODO: Recurse into `_stats` to find additional types.
      // A `Type.Refine` represents syntax: A { def f: Int }
      case Type.Refine(typeOpt, _stats)  => typeOpt.toVector.flatMap(extractNamesFromTypeTree(_))
      case Type.Existential(tpe, _stats) => extractNamesFromTypeTree(tpe)
      case Type.Annotate(tpe, _annots)   => extractNamesFromTypeTree(tpe)
      case Type.Lambda(_tparams, tpe)    => extractNamesFromTypeTree(tpe)
      case Type.Bounds(loOpt, hiOpt) =>
        loOpt.toVector.flatMap(extractNamesFromTypeTree(_)) ++ hiOpt.toVector.flatMap(
          extractNamesFromTypeTree(_)
        )
      case Type.ByName(tpe)   => extractNamesFromTypeTree(tpe)
      case Type.Repeated(tpe) => extractNamesFromTypeTree(tpe)
      // TODO: Should we extract a type from _tpe?
      // `Type.Match` represents this Scala 3 syntax: type T = match { case A => B }
      case Type.Match(_tpe, cases) => cases.toVector.flatMap(extractNamesFromTypeTree(_))
      case TypeCase(pat, body) => extractNamesFromTypeTree(pat) ++ extractNamesFromTypeTree(body)
      case _                   => Vector()
    }
  }

  def recordProvidedName(
      symbolName: String,
      sawClass: Boolean = false,
      sawTrait: Boolean = false,
      sawObject: Boolean = false,
      recursive: Boolean = false
  ): Unit = {
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
          recursive = existingSymbol.recursive || recursive
        )
        providedSymbols(symbolName) = newSymbol
      } else {
        providedSymbols(symbolName) = ProvidedSymbol(
          sawClass = sawClass,
          sawTrait = sawTrait,
          sawObject = sawObject,
          recursive = recursive
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
    withNamePart(
      name,
      () => {
        apply(templ.early)
        apply(templ.stats)
      }
    )
  }

  def visitMods(mods: List[Mod]): Unit = {
    mods.foreach({
      case Mod.Annot(init) =>
        apply(init) // rely on `Init` extraction in main parsing match code
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

      // TODO: should object already be recursive?
      // an object is recursive if extends another type because we cannot figure out the provided types
      // in the parents, we just mark the object as recursive (which is indicated by non-empty inits)
      val recursive = !templ.inits.isEmpty
      recordProvidedName(name, sawObject = true, recursive = recursive)

      // visitTemplate visits the inits part of the template in the outer scope,
      // however for a package object the inits part can actually be found both in the inner scope as well (package inner).
      // therefore we are not calling visitTemplate, calling all the apply methods in the inner scope.
      // issue https://github.com/pantsbuild/pants/issues/16259
      withNamePart(
        name,
        () => {
          templ.inits.foreach(init => apply(init))
          apply(templ.early)
          apply(templ.stats)
        }
      )
    }

    case Defn.Class(mods, nameNode, tparams, ctor, templ) => {
      visitMods(mods)
      val name = extractName(nameNode)
      recordProvidedName(name, sawClass = true)
      apply(tparams)
      apply(ctor)
      visitTemplate(templ, name)
    }

    case Defn.Trait(mods, nameNode, tparams, ctor, templ) => {
      visitMods(mods)
      val name = extractName(nameNode)
      recordProvidedName(name, sawTrait = true)
      apply(tparams)
      apply(ctor)
      visitTemplate(templ, name)
    }

    case Defn.Object(mods, nameNode, templ) => {
      visitMods(mods)
      val name = extractName(nameNode)

      // TODO: should object already be recursive?
      // an object is recursive if extends another type because we cannot figure out the provided types
      // in the parents, we just mark the object as recursive (which is indicated by non-empty inits)
      val recursive = !templ.inits.isEmpty
      recordProvidedName(name, sawObject = true, recursive = recursive)

      // If the object is recursive, no need to provide the symbols inside
      if (recursive)
        withSuppressProvidedNames(() => visitTemplate(templ, name))
      else
        visitTemplate(templ, name)
    }

    case Defn.Type(mods, nameNode, _tparams, body) => {
      visitMods(mods)
      val name = extractName(nameNode)
      recordProvidedName(name)
      extractNamesFromTypeTree(body).foreach(recordConsumedSymbol(_))
    }

    case Defn.Val(mods, pats, decltpe, rhs) => {
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

    case Defn.Def(mods, nameNode, tparams, params, decltpe, body) => {
      visitMods(mods)
      val name = extractName(nameNode)
      recordProvidedName(name)

      decltpe.foreach(tpe => {
        extractNamesFromTypeTree(tpe).foreach(recordConsumedSymbol(_))
      })

      apply(tparams)
      params.foreach(param => apply(param))

      withSuppressProvidedNames(() => apply(body))
    }

    case Decl.Def(mods, _nameNode, tparams, params, decltpe) => {
      visitMods(mods)
      extractNamesFromTypeTree(decltpe).foreach(recordConsumedSymbol(_))
      apply(tparams)
      params.foreach(param => apply(param))
    }

    case Decl.Val(mods, _pats, decltpe) => {
      visitMods(mods)
      extractNamesFromTypeTree(decltpe).foreach(recordConsumedSymbol(_))
    }

    case Decl.Var(mods, _pats, decltpe) => {
      visitMods(mods)
      extractNamesFromTypeTree(decltpe).foreach(recordConsumedSymbol(_))
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
                false
              )
            }
            case _ =>
          }
        })
      })
    }

    case Init(tpe, _name, argss) => {
      extractNamesFromTypeTree(tpe).foreach(recordConsumedSymbol(_))
      argss.foreach(_.foreach(apply))
    }

    case Term.Param(mods, _name, decltpe, _default) => {
      visitMods(mods)
      decltpe.foreach(tpe => {
        extractNamesFromTypeTree(tpe).foreach(recordConsumedSymbol(_))
      })
    }

    case Type.Param(mods, _name, _tparams, bounds, _vbounds, cbounds) => {
      visitMods(mods)
      extractNamesFromTypeTree(bounds).foreach(recordConsumedSymbol(_))
      cbounds.flatMap(extractNamesFromTypeTree(_)).foreach(recordConsumedSymbol(_))
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
      apply(node.qual)
    }

    case node @ Term.Name(_) => {
      val name = extractName(node)
      recordConsumedSymbol(name)
    }

    case node => super.apply(node)
  }

  def gatherProvidedSymbols(): SortedSet[Analysis.ProvidedSymbol] = {
    providedSymbolsByScope
      .flatMap({ case (scopeName, symbolsForScope) =>
        symbolsForScope.map { case (symbolName, symbol) =>
          Analysis.ProvidedSymbol(qualifyName(scopeName, symbolName), symbol.recursive)
        }.toVector
      })
      .to(SortedSet)
  }

  def gatherEncodedProvidedSymbols(): SortedSet[Analysis.ProvidedSymbol] = {
    providedSymbolsByScope
      .flatMap({ case (scopeName, symbolsForScope) =>
        val encodedSymbolsForScope = symbolsForScope.flatMap({
          case (symbolName, symbol) => {
            val encodedSymbolName = NameTransformer.encode(symbolName)
            val result = ArrayBuffer[Analysis.ProvidedSymbol](
              Analysis.ProvidedSymbol(encodedSymbolName, symbol.recursive)
            )
            if (symbol.sawObject) {
              result.append(Analysis.ProvidedSymbol(encodedSymbolName + "$", symbol.recursive))
              result.append(
                Analysis.ProvidedSymbol(encodedSymbolName + "$.MODULE$", symbol.recursive)
              )
            }
            result.toVector
          }
        })

        encodedSymbolsForScope.map(symbol => symbol.copy(name = qualifyName(scopeName, symbol.name)))
      })
      .to(SortedSet)
  }

  def toAnalysis: Analysis = {
    Analysis(
      providedSymbols = gatherProvidedSymbols(),
      providedSymbolsEncoded = gatherEncodedProvidedSymbols(),
      importsByScope = importsByScope,
      consumedSymbolsByScope = consumedSymbolsByScope,
      scopes = scopes.toVector
    )
  }

  private def qualifyName(qualifier: String, name: String): String = {
    if (qualifier.length > 0) s"$qualifier.$name"
    else name
  }
}

object ScalaParser {
  def analyze(pathStr: String, scalaVersion: String, source3: Boolean): Analysis = {
    val path = java.nio.file.Paths.get(pathStr)
    val bytes = java.nio.file.Files.readAllBytes(path)
    val text = new String(bytes, "UTF-8")

    val dialect =
      scalaVersion.take(4) match {
        case "2.10"            => dialects.Scala210
        case "2.11"            => dialects.Scala211
        case "2.12" if source3 => dialects.Scala212Source3
        case "2.12"            => dialects.Scala212
        case "2.13" if source3 => dialects.Scala213Source3
        case "2.13"            => dialects.Scala213
        case "3.0"             => dialects.Scala3
        case _ =>
          if (scalaVersion.take(2) == "3.") dialects.Scala3
          else dialects.Scala213
      }

    val input = dialect(Input.VirtualFile(path.toString, text))

    val tree = input.parse[Source].get

    val analysisTraverser = new SourceAnalysisTraverser()
    analysisTraverser.apply(tree)
    analysisTraverser.toAnalysis
  }

  def main(args: Array[String]): Unit = {
    val outputPath = java.nio.file.Paths.get(args(0))
    val pathStr = args(1)
    val scalaVersion = args(2)
    val source3 = args(3).toBoolean
    val analysis = analyze(pathStr, scalaVersion, source3)

    val json = analysis.asJson.noSpaces
    java.nio.file.Files.write(
      outputPath,
      json.getBytes(),
      java.nio.file.StandardOpenOption.CREATE_NEW,
      java.nio.file.StandardOpenOption.WRITE
    )
  }
}
