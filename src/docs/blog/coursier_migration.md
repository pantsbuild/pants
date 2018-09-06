# Twitter's Coursier Migration

**08/31/2018**

**Authors and Contributors**

[[Yi Cheng|https://twitter.com/yidcheng]], [[Nora Howard|https://twitter.com/baroquebobcat]], and [[Dorothy Ordogh|https://twitter.com/dordogh]] at Twitter Engineering Effectiveness - Build.

**Timeframe**

Twitter migrated to Coursier from Ivy during Q1 2018.

## Tl;dr

This blog post discusses the motivation, preparation work, deployment processes, and results of replacing Ivy with Coursier in Pants.

## Background

Twitter uses Pants as the build tool for the main repository which accounts for the majority of development. Inevitably, projects can get large with hundreds or thousands of source and binary (“3rdparty”) dependencies.

At this scale, an IDE is also commonly used to help developer productivity. Regardless of which IDE is used, Pants will need to tell it where all the 3rdparty dependencies are located. For JVM projects specifically, that means resolving maven style 3rdparty artifacts.

In some cases build tools (such as Gradle and Maven) implement their own 3rdparty resolution logic, whereas others (such as Pants and SBT) use a standalone tool called Ivy to do the resolve via certain APIs. This post discusses why and how Twitter adopted another 3rdparty resolve tool called Coursier to replace Ivy and how much impact it made.

## Motivation and Initial Investigation

For a common project with relatively few 3rdparty dependencies (<20), the resolve time for Ivy is rather minimal, typically a few seconds to resolve and a few more to download the artifacts with reasonable network speed.

However, Ivy is not so scalable with a large set of 3rdparty dependencies. The table below shows the measurement in the initial investigation on cacheless resolve. We did so by manually converting the XML passed to Ivy to the rough command line equivalent for Coursier [[\[1\]|#1-example-of-translation-for-pants-jar_library-target-to-coursier-command-line]] [[\[2\]|#2-why-3rdparty-resolve-caching-wasnt-too-great]].

| Project | # of root level 3rdparty dependencies | # of transitive 3rdparty dependencies (obtained later for this blogpost) | Ivy   | Coursier (20 concurrent connections) |
|---------|---------------------------------------|--------------------------------------------------------------------------|-------|--------------------------------------|
| A       | 140                                   | 231                                                                      | 290s  | 80s                                  |
| B       | 330                                   | 480                                                                      | 1468s | 132s                                 |

## Pre-Migration - Changes Made to Coursier

The initial investigation gave us the motivation to pursue Coursier. However, there were still some gaps before Pants could fully utilize it. It was important to test the changes made to Coursier, i.e. testing all JVM targets in CI environment in our case. All changes below were iterated with this process to assure quality.

### Usability

#### JSON Report

Since Pants is written in Python, it needs to call Coursier via command line, so a JSON report from Coursier was implemented to facilitate this as the main API.

[[https://github.com/coursier/coursier/pull/692]]

There was also a follow up patch to further improve the JSON report to support more detailed coordinate specification.

[[https://github.com/coursier/coursier/pull/782]]

#### Granularity

Previously Coursier’s command line could only specify exclusions and classifiers on a global level, so we made it more granular: to the module level.

[[https://github.com/coursier/coursier/pull/735]]

[[https://github.com/coursier/coursier/pull/692]]

#### Direct URL Fetching

We also added support for fetching an artifact with an arbitrary URL, which is commonly used to iterate against a jar that’s not published.

[[https://github.com/coursier/coursier/pull/774]]

### Reliability

Some artifacts are rather large (on the scale of 100-200MB), so there’s a chance the download may fail. Previously this would cause a bad artifact corrupting the local cache, which was later removed with the patch.

[[https://github.com/coursier/coursier/pull/797]]

### Visibility

To better help with the migration, such as comparing the result with Ivy and sanity check, we needed Coursier to print out the resolve graph correctly.

[[https://github.com/coursier/coursier/pull/671]]

## The Migration Process

The actual migration was done in two major phases: 1) Coursier only for IDE project import, and then 2) Coursier for all Pants commands

### Phase 1 - IDE Only

There are two reasons to use IDE as the initial testing ground.

* Being less critical. Twitter developers only use IDE for code assistance such as syntax highlighting and code navigation. Whereas releasing and test running will still use Ivy code path. Therefore, any bug encountered initially in IDE will not affect production [[\[3\]|#3-example-intellij-pants-plugin-issue]].

* To further prove out the performance impact at scale. This provided early feedback of Coursier usage at scale as opposed to the sampling in the initial investigation.

The process was done by having IntelliJ Pants Plugin to recognize a special config .ij.import.rc under the repo root ([[https://github.com/pantsbuild/intellij-pants-plugin/pull/324]]) which overwrites the default resolver Ivy to Coursier. Additionally, developers were always given the option to fall back to Ivy in case they were blocked by Coursier.

### Phase 2 - All Pants Commands

Switching to Coursier for all Pants commands was much riskier because that was what developers used every day for the actual compilation and what CI infrastructure used for testing and deployment. To reduce the risk, we broke it down further:

* Experimentally turn on Coursier for a percentage of developer laptops and increase enrollment percentage slowly over 2-3 weeks. If any blocking issue was observed, we immediately tuned it back to 0.
* Aggregating all the deployment targets, and compare the resolution differences between Ivy and Coursier [[\[4\]|#4-resolve-difference-investigation]], i.e A/B testing.

#### Issues to notice

##### Resolve Differences and Safety

Different resolves for the same set of 3rdparty dependencies can occur between Ivy and Coursier for various reasons. In the end, they are separate tools, so their implementations or bugs are different even though they are supposed to respect the same maven specification.

In multiple instances, we found that Ivy does not resolve correctly accordingly to Maven's “standard” [[\[5\]|#5-resolve-differenceserrors-between-ivy-and-coursier]]. Although Coursier's resolves may be more correct, it DOES NOT mean applications will always work as intended with the correct but different resolve. Sometimes it works accidentally with the wrong resolve. That is why we need to be careful.

That said, if the resolves are the same between Ivy and Coursier, then it is normally safe. In some edge cases, the order of JVM class loading would make a difference.

##### Caching Discrepancy

* Between Ivy and Coursier. With the expected resolve differences explained above, cache keys for compilation will be different between Ivy and Coursier since 3rdparty dependencies are part of the cache key. We rely on CI infrastructure to populate caches, so it needs to populate the compile cache resulting from both Ivy and Coursier until the migration is completed.
* Some resolves are platform dependent, meaning that even if two builds have the same resolver, one cannot reuse the cache from the other if they are built on different platforms, e.g. MacOS and Linux. For this very reason, we turned off Coursier enrollment before finding and settling the difference between platforms [5].

## Limitation
At the end of the day, unit tests typically would only run part of the 3rdparty dependencies' code that an application depends on, so there is no way to fully validate whether any transitive 3rdparty dependencies are functioning correctly. Hence the recommendation we provided for the owners of all JVM applications with different resolves was to have them go through any integration tests or staging environment if applicable.

## Result

### Pants export (used for intellij)
* p95 down from 130s to 72s
* p90 down from 90s to 51s
### Pants resolve (used for compile/test)
* p95 down from 45s to 23s
* p90 unchanged

The weekly savings on user laptop, (average Coursier time - average Ivy time) * total invocation, is about 40 hours, i.e. equivalent to a full head count. This may not seem a lot given the size of Twitter, but keep in mind that this is the time developers have no choice but to wait for.

Additional note: once caches are on disk, warm resolve is the same between Ivy and Coursier. Hence the improvement is mostly above the p90 range.

## Appendix

### 1. Example of translation for Pants jar_library target to Coursier command line
```
jar_library(
  name='specs2-junit_2.11',
  jars=[
    jar(org='org.specs2', name='specs2-junit_2.11', rev='3.8.9'),
  ],
)
```

Translation to Ivy-resolve.xml:
```
<dependency org="org.specs2" name="specs2-junit_2.11" rev="3.8.9">
   <conf name="default" mapped="default" />
   <artifact name="specs2-junit_2.11" type="jar" />
</dependency>
```

Translation to Coursier CLI:
```
./coursier fetch org.specs2:specs2-junit_2.11:3.8.9
```

### 2. Why 3rdparty resolve caching wasn’t too great?

Two major steps are involved when doing 3rdparty resolve

* Figure out what artifacts are needed
* Download them

The goal and benefit of caching 3rdparty resolve is to reuse the result from step 1, likely from another machine, thus only needing to do step 2 because not all artifacts are present.

Currently Pants resolves 3rdparty dependencies per context. For example, with target A and target B
resolve(A) => SetA jars
resolve(B) => SetB jars
resolve(A + B) is not necessarily (SetA union SetB) jars, because there may be conflicts to manage and SNAPSHOT to recompute.

Since Pants command can involve an arbitrary number of targets. Given n targets users are interested in, the total number of combination is 2n, so the likelihood of cache hit would be low.

There is also the practical aspect in terms of implementation and maintenance cost vs benefit.

### 3. Example IntelliJ Pants Plugin issue
Exclude jars imported into the project for IntelliJ Junit/Scala runner [[https://github.com/pantsbuild/intellij-pants-plugin/pull/331]]

### 4. Resolve difference investigation

This following script compares the resolves done by Ivy and Coursier on the same target.
```
target=$1

echo "target: $target"
./pants --resolver-resolver=coursier export --output-file=a.out $target &> /dev/null \
&& jq '.libraries | keys'  < a.out  > coursier_libs \
&& ./pants --resolver-resolver=ivy export --output-file=a.out $target &> /dev/null \
&& jq '.libraries | keys'  < a.out  > ivy_libs

diff coursier_libs ivy_libs
```

Gives a simpler version of the diff is captured below. For example:

`<` means what Coursier has

`>` means what Ivy has

```
<   "asm:asm:3.1",
---
>   "asm:asm:3.2",
128d127
<   "org.apache.hadoop:hadoop-yarn-server-nodemanager:2.6.0.t01",
130c129
<   "org.apache.httpcomponents:httpcore:4.2.4",
---
>   "org.apache.httpcomponents:httpcore:4.2.5",
```

To examine the difference in detail, we need to obtain the reports from Ivy and Coursier, then compare them manually.
Ivy:
```
./pants --no-cache-resolve-ivy-read --resolver-resolver=ivy invalidate resolve.ivy --open --report <target>
```

Coursier:
```
./pants --resolver-resolver=coursier resolve.coursier --report <target>
```

### 5. Resolve differences/errors between Ivy and Coursier

#### Platform dependent resolve

[[https://github.com/coursier/coursier/issues/700]]

* It turned out that the build was previously working accidentally with Ivy resolve. The should-be platform dependent jar was used by our build in both linux and MacOS builds because Ivy ignored the platform specific requirement. Hence switching to Coursier broke the build. The solution was to force fetching the platform dependent jar regardless of the platform.
* This also caused complication in caching, because of 3rdparty jars are part of the compile cache key, so if a 3rdparty jar is platform dependent, that means cache populated by CI on linux cannot be reused on MacOS.

#### Dependency management via parent pom

[[https://github.com/coursier/coursier/issues/809]]

* org.apache.httpcomponents:httpcore:4.2.5 (Ivy) -> org.apache.httpcomponents:httpcore:4.2.4 (Coursier). The difference is harmless, but the correct one should be 4.2.4.

## Related links

[[How to use Coursier in Pants|pants('examples/src/java/org/pantsbuild/example:readme')#toolchain]]

[[Coursier repo|https://github.com/coursier/coursier]]
