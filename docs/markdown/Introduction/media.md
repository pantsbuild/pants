---
title: "Resource hub"
slug: "media"
excerpt: "Learn more about Pants and related topics from these talks, posts and podcasts featuring Pants contributors and users."
hidden: false
createdAt: "2021-04-18T17:27:18.361Z"
---

## Case Studies

### Tweag

January 3, 2023
"From adopting Pants, to generalizing our CI to multiple Python versions" <https://blog.pantsbuild.org/tweag-case-study/>

> Describes why and how the maintainers of Bazel's Haskell rules chose to use Pants for a client's Python monorepo. Also covers some gotchas for newcomers.

### Oxbotica

November 4, 2022
"Introducing Pants to Oxbotica"
<https://blog.pantsbuild.org/introducing-pants-to-oxbotica/>

> Self-driving vehicle company's successful journey to adopting Pants locally and in CI.


### Coinbase

September 1, 2022  
"Part 1: Building a Python ecosystem for efficient and reliable development"  
<https://blog.coinbase.com/building-a-python-ecosystem-for-efficient-and-reliable-development-d986c97a94a0>

> Describes how the company developed an efficient, reliable Python ecosystem using Pants, and solved the challenge of managing Python applications at a large scale at Coinbase.


October 27, 2022
"Part 2: Building a Python ecosystem for efficient and reliable development"  
<https://www.coinbase.com/blog/part-2-building-a-python-ecosystem-for-efficient-and-reliable-development>

> Explains the technical details of the continuous integration/continuous delivery (CI/CD) infrastructure and dependency management of the company's Python ecosystem.

### IBM Developer Blog

August 24, 2022  
"Incrementally migrating a Python monorepo from Bazel to Pants"  
<https://developer.ibm.com/blogs/case-study-incrementally-migrating-a-python-monorepo-from-bazel-to-pants/>  

> Watson Orders is an IBM Silicon Valley based technology development group targeting the development of world-class conversational AI. This posts walks through the process of migrating off Bazel, where they maintained 19,000 lines of BUILD file metadata, to Pants where that was slashed to 2,400 lines thanks to [dependency inference](doc:how-does-pants-work#dependency-inference). CI build time for PRs dropped from 10-12 minutes with Bazel to under 4 minutes with Pants.

### Astranis Space Technologies

August 12, 2022  
"Astranis Case Study: Wrangling Python In a Monorepo"
<https://blog.pantsbuild.org/astranis-case-study-wrangling-python-in-a-monorepo/>  

> <i>"...We found it incredibly easy to hook in our existing remote caching systems to Pants, and added other nice features like running tailor in a check-only mode to highlight any inconsistencies in our repo. As a side benefit, Pants has helped us gain better insight into our repository by being able to easily scan for and report the transitive dependencies of modules. Having that insight has helped us plan out how to minimize the coupling of our modules..."</i>

### Twitter Engineering

December 31, 2021  
"Advancing Jupyter Notebooks at Twitter - Part 1"  
<https://blog.twitter.com/engineering/en_us/topics/infrastructure/2021/advancing-jupyter-notebooks-at-twitter---part-1--a-first-class-d>  

> About the intersection of Twitter data science, monorepos, Pants, Pex, and the [pants-jupyter-plugin](https://github.com/pantsbuild/pants-jupyter-plugin).

### iManage

October 2, 2021  
"Putting Pants On: One Thing We Did Right After 5 Years with Django"  
<https://g-cassie.github.io/2021/10/02/django-pants.html>


## Tutorials

### Doctrine.fr Engineering blog

Nov 25, 2022  
"Industrialized Python code with Pylint plugins in Pants"  
<https://medium.com/doctrine/industrialized-python-code-with-pylint-plugins-in-pants-321d9cbad07a>

> What if you needed to put strict code convention rules through a linter and apply them with the help of Pants?

### Suresh Joshi

April 4, 2022  
"It's Pants Plugins All the Way Down"  
<https://sureshjoshi.com/development/pants-plugin-code-quality>  

> A follow-up to "Your first Pants plugin" detailing how to manage code quality via plugins, continuous integration checks, and pre-commit hooks.

January 25, 2022  
"Your first Pants plugin"  
<https://sureshjoshi.com/development/first-pants-plugin>  

> A newcomer's walk-through of the code and experience of writing one's first Pants plugin.

### Gordon Cassie

October 30, 2021  
"Getting Started With Pants and Django"  
<https://g-cassie.github.io/2021/10/30/django-pants-tutorial-pt1.html>


## Podcasts

### The Real Python Podcast

Episode 137: Start Using a Build System & Continuous Integration in Python
December 16, 2022

> What advantages can a build system provide for a Python developer? What new skills are required when working with a team of developers? Pants core maintainer and co-author Benjy Weinberger discusses Pants and getting started with continuous integration (CI).

### Happy Path Programming Podcast

Episode 72: Pants Makes Developers Happier and More Productive, with Benjy Weinberger
December 16, 2022
<https://anchor.fm/happypathprogramming/episodes/72-Pants-Makes-Developers-Happier--More-Productive-with-Benjy-Weinberger-e1sc1uj>

### Humans of Devops

Season 3, Episode 69: The Curse of Knowledge  
March 7, 2022  
<https://audioboom.com/posts/8043212-the-curse-of-knowledge-with-eric-arellano-and-nick-grisafi>  

> Pants core maintainer Eric Arellano and Pants contributor Nick Grisafi discuss what Pants team has learned from philosophical concepts such as The Curse of Knowledge, Beginners Mind, and The Power of the Outsider.

### Podcast.\_\_init\_\_

Episode 352: Simplify And Scale Your Software Development Cycles By Putting On Pants (Build Tool)  
February 14, 2022  
<https://www.pythonpodcast.com/pants-software-development-lifecycle-tool-episode-352/>  

> Pants core maintainers Stu Hood, Eric Arellano, and Andreas Stenius guest.

### Software Engineering Daily

Build Tools with Benjy Weinberger  
January 17, 2022  
<https://softwareengineeringdaily.com/2022/01/17/build-tools-with-benjy-weinberger/>

### Semaphore Uncut

Episode 33: Monorepo and Building at Scale  
April 13, 2021  
<https://semaphoreci.com/blog/monorepo-building-at-scale>  

> Pants core maintainer Benjy Weinberger guests.

### Angelneers

Episode 28: Shifting Build Execution Paradigm  
February 12, 2021  
<https://angelneers.com/podcast/28-shifting-build-execution-paradigm/>  

> Pants core maintainer Benjy Weinberger guests.

### Podcast.\_\_init\_\_

Episode 290: Pants Has Got Your Python Monorepo Covered  
November 23, 2020  
<https://www.pythonpodcast.com/pants-monorepo-build-tool-episode-290/>  

> Pants core maintainers Stu Hood and Eric Arellano guest.


## Posts & Articles

### Inside Doctrine
November 25, 2022
"Industrialized python code with Pylint plugins in Pants"
<https://medium.com/doctrine/industrialized-python-code-with-pylint-plugins-in-pants-321d9cbad07a>

### Dev.to

July 25, 2022  
"Better CI/CD caching with new-gen build systems"  
<https://dev.to/benjyw/better-cicd-caching-with-new-gen-build-systems-3aem>  

> How the cache solutions offered by CI providers work, why they are often of limited benefit, and how Pants supports a much more effective caching paradigm. 

### Software Development Times

January 18, 2022  
"The monorepo approach to code management"  
<https://sdtimes.com/softwaredev/the-monorepo-approach-to-code-management/> 

> <i>"If you’re responsible for your organization’s codebase architecture, then at some point you have to make some emphatic choices about how to manage growth in a scalable way..."</i>

### Semaphore Blog

June 9, 2021  
"Building Python Projects at Scale with Pants"  
<https://t.co/WuXPqwQ9KX>

### Towards Data Science

Sept 3, 2020  
"Building a monorepo for Data Science with Pants Build"  
<https://towardsdatascience.com/building-a-monorepo-for-data-science-with-pantsbuild-2f77b9ee14bd>

## Talks

### PyCon AU 2023

#### Packaging for serverless: effortless? Doubtless!
August 19, 2023
<https://www.youtube.com/watch?v=YwuUI6bYUh0&t=5s&pp=ygUwUGFja2FnaW5nIGZvciBzZXJ2ZXJsZXNzOiBlZmZvcnRsZXNzPyBEb3VidGxlc3Mh>

> Pants team member Huon Wilson talks about how the Pants build system works in practice for getting our Python code running in AWS Lambdas in production, and how it's improved upon other common practices we previously used.

### Pycon China 2022

#### [LIGHTNING TALK] 沈达：Pants，Python工程化必备构建工具
December 17, 2022
<https://www.bilibili.com/video/BV1L3411S76J/>

> 这是一次闪电演讲，在此次演讲中，Darcy Shen简明扼要地介绍了他使用Pants做Python项目工程化的经历。

### Tubi China

#### Pants : Python 工程化的必备工具

December 1, 2022
<https://www.bilibili.com/video/BV1L3411S76J/>

> In this internal tech talk, TubiTV data engineer Darcy Shen illustrates: one command line to launch JupyterLab with a proper dependency set, writing Python snippets just using a web browser, best practices for managing Python projects with Pants, and smart dependency inference of Pants.

### Pycon Japan

#### Modernizing development workflow for a 7-year old 74K LoC Python project using Pantsbuild

October 15, 2022
<https://www.youtube.com/watch?v=SwaaQoHdqPM>

> Mono-repository or not? That is a boggling question for many medium-to-large-sized development teams. As a growing company, Lablup had to onboard new hires quickly while coping with flooding customer requests and increasing codebase complexity. They merged 7 repositories into a single one and migrated to the Pantsbuild system, a Python-friendly modern build system. Here is the story, as told by CTO Joongi Kim.

### Pycon Korea

#### Pantsbuild를 활용하여 대규모 Python 프로젝트를 모노리포로 이전하기

October 2, 2022
<https://youtu.be/r2FpfmcoL5M>

> 이 세션에서는 Backend.AI 오픈소스 프로젝트를 Pantsbuild 도구를 활용하여 모노리포(mono-repo)로 이전한 과정을 소개합니다. Backend.AI 프로젝트는 7년 동안 쌓인 7만 4천 줄 이상의 Python 코드로 작성되어 있으며, 다수의 패키지를 조합하고 설치해야 전체적인 기능 개발 및 테스트가 가능한 상당한 복잡도가 있는 코드베이스를 가지고 있습니다. 프로젝트 참여 인원의 규모가 늘어나고 내부의 코드도 복잡해지면서 패키지 단위로 저장소를 관리하는 것이 개발 프로세스의 병목을 가져왔고, 이 문제를 타개하기 위해 모노리포 도입을 고민하고 결정하였습니다. 모노리포가 모든 경우에 항상 정답은 아니지만, 개발팀의 규모, 내부 의존성들의 현재와 미래 예상 복잡도, 조직의 운영 방식, 코드의 변경이 영향을 미치는 범위, 릴리즈 주기, 이슈 관리 도구인 GitHub의 프로젝트 보드 기능 제약 등의 다양한 조건을 고려하였을 때 현 시점에서 합리적 전환이라 생각하였습니다. 특히, 하나의 이슈를 해결하기 위해 여러 개의 저장소에 여러 개의 pull request를 작성하고 이를 리뷰하는 과정은 개발자들의 컨텍스트 스위칭 오버헤드를 크게 증가시켰으며, 특정 저장소의 pull request 작성 자체를 빼먹는다거나 branch 통일을 깜빡하여 오류를 겪는 문제들이 반복되었습니다. 모노리포 전환 과정에서는 내외부 의존성 관리를 최대한 명시화 및 자동화하기 위해 Pantsbuild를 도입하였습니다. Pantsbuild는 Python 생태계를 우선적으로 지원하는 현대적 빌드 도구로, 강력한 캐싱과 빌드 및 CI 관련 작업의 병렬 실행을 잘 지원합니다. 본 발표에서는 Pantsbuild를 원활하게 사용할 수 있도록 기존 Backend.AI 저장소들을 어떻게 합쳤는지와 함께, Pantsbuild의 플러그인 작성 및 Backend.AI의 동적 모듈 로딩 메커니즘 대응을 통해 Pantsbuild에 적응해나간 과정도 함께 소개합니다. 기본적인 마이그레이션 이후에도 개발팀에서 겪었던 추가적인 문제들과 그런 문제들을 어떻게 대응하였는지에 대한 사례도 함께 설명합니다. 이 세션을 통해 대규모 Python 프로젝트의 모노리포 구성에 대한 사례와 힌트를 파악해가실 수 있는 시간이 되기를 바랍니다.


### AWS Community Day Bay Area 2022

#### When Projects Grow: CI/CD at scale

September 9, 2022
<https://www.youtube.com/watch?v=bLBpM3I3GHw>

> Pants maintainer Josh Reed gives a talk about the challenges about running CI on a large monolith codebase, and mentions Pants as part of the ensemble of soultions to help wrangle the complexity that comes with scale.

### Pycon 2022

#### "Hermetic Environments in Pantsbuild" aka "Fast and Reproducible Tests, Packaging, and Deploys with Pantsbuild"

April 24, 2022  
<https://www.youtube.com/watch?v=0INmW9KaAp4>  
<https://speakerdeck.com/chrisjrn/hermetic-environments-in-pantsbuild-31d03419-8a15-4cd3-9041-b817b8924b3c>  

> Pants maintainer Chris Neugebauer gives a deep dive into the sandboxing model used by Pants, the priorities driving its design, and the pros and cons.

#### [LIGHTNING TALK] "Stop Running Your Tests"

April 23, 2022  
<https://youtu.be/r-rpo4Xm_lM?t=2799>  

> Chris Neugebauer gives a swift and cheeky introduction to Pants.

### EuroPython 2021

#### "Python monorepos: what, why and how"

July 30, 2021  
<https://www.youtube.com/watch?v=p4stnR1gCR4>  
<https://speakerdeck.com/benjyw/python-monorepos-what-why-and-how-europython-2021>  

> A discussion of the advantages of monorepos for Python codebases, and the kinds of tooling and processes we can use to make working in a Python monorepo effective.

### Build Meetup 2021

#### "Faster Incremental Builds with Speculation"

June 24, 2021  
<https://meetup.build/>

### Djangocon Europe 2021

#### "Managing Multiple Django Services in a Single Repo"

June 3, 2021  
<https://www.youtube.com/watch?v=Glillzb_TqQ>  
<https://cfp.2021.djangocon.eu/2021/talk/CTXYZE/>

### Pyninsula Meetup

#### "Effective Python Monorepos with the Pants Build System"

May 25, 2021  
<https://youtu.be/a15T-D-f9a8?t=1225> (starts at timestamp 20:25)

### Pycon 2021

#### "Creating Extensible Workflows With Off-Label Use of Python"

May 14, 2021  
<https://youtu.be/HA5gzP4Ncao>  
<https://speakerdeck.com/benjyw/creating-extensible-workflows-with-off-label-use-of-python>  

> A dive into how Pants 2 benefits from making unconventional use of certain Python 3 features.

#### "Cuándo Usar Extensiones Nativas en Rust: Rendimiento Accesible y Seguro"

May 14, 2021  
<https://youtu.be/gMFY0uUQexE>  
<https://speakerdeck.com/ericarellano/cuando-usar-extensiones-nativas-en-rust-rendimiento-accesible-y-seguro>  

> Cuando hay problemas de rendimiento, las extensiones nativas de Python se empoderan para mejorar el rendimiento del "critical path", y también seguir usando Python y evitar una reinscripción costosa.

### Pycon Israel 2021

#### "Python Monorepos: What, Why, and How"

May 3, 2021  
<https://www.youtube.com/watch?v=N6ENyH4_r8U>  
<https://speakerdeck.com/benjyw/python-monorepos-what-why-and-how>

### SF Python Meetup

#### "How the Pants Build System Leverages Python 3 Features"

May 13, 2020  
<https://www.youtube.com/watch?v=mLyW6oAExW0>  
<https://speakerdeck.com/benjyw/how-the-pants-build-system-leverages-python-3-features>


## YouTube

### Pants Build project's official channel

Home: <https://www.youtube.com/@pantsbuild>  
Pants Build 2 Tour: <https://www.youtube.com/playlist?list=PLwPRXwjURiOzXjgqydxZE9RVjZqaB6OXb>

## Repositories

### Official examples

[Pantsbuild-maintained example repos](https://github.com/orgs/pantsbuild/repositories?q=example&type=source&language=&sort=stargazers), focusing on language support, Docker, Django, code generation, and other key features.

### Example: Python with Pants and PEX

A running example of the Pants Build system and Python packaging with PEX.
<https://github.com/StephanErb/pexample>

### Example: Pylint custom linter rules for a Python project using Pants

A ready-to-use example of a repository that contains a Python project and Pylint custom linter rules.
<https://github.com/DoctrineLegal/demo-pants-pylint>

### liga

Pants makes open source project [`liga`](https://github.com/liga-ai/liga) more modular and extensible by replacing setuptools.

### Backend.ai

Lablup CTO Joongi Kim's Pycon Japan slides illustrate how open source project [Backend.ai](https://github.com/lablup/backend.ai) takes advantage of Pants in [daily development workflows](https://docs.backend.ai/en/latest/dev/daily-workflows.html).

### StackStorm

A showcase of open source project [StackStorm's upcoming migration to Pants](https://github.com/StackStorm/st2).

> 📘 Suggest a Resource
> 
> Got more Pants-related content such as talks, case studies, interviews, tutorials, etc to include on this page? We invite you to suggest adding it. Just click _Suggest Edits_ at the top right of the page, or [let us know](doc:getting-help).
