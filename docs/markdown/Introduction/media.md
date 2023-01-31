---
title: "Resource hub"
slug: "media"
excerpt: "Learn more about Pants and related topics from these talks, posts and podcasts featuring Pants contributors and users."
hidden: false
createdAt: "2021-04-18T17:27:18.361Z"
updatedAt: "2023-01-04T22:02:38.457Z"
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

> Watson Orders is an IBM Silicon Valley based technology development group targeting the development of world-class conversational AI. This posts walks through the process of migrating off Bazel, where they maintained 19,000 lines of BUILD file metadata, to Pants where that was slashed to 2,400 lines thanks to [dependency inference](doc:/how-does-pants-work#dependency-inference). CI build time for PRs dropped from 10-12 minutes with Bazel to under 4 minutes with Pants.

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

Home: <https://www.youtube.com/channel/UCCcfCbDqtqlCkFEuENsHlbQ>  
Pants Build 2 Tour: <https://www.youtube.com/playlist?list=PLwPRXwjURiOzXjgqydxZE9RVjZqaB6OXb>

## Repositories

### Example: Python with Pants and PEX

"A running example of the Pants Build system and Python packaging with PEX."  
<https://github.com/StephanErb/pexample>

> 📘 Suggest a Resource
> 
> Got more Pants-related content such as talks, case studies, interviews, tutorials, etc to include on this page? We invite you to suggest adding it. Just click _Suggest Edits_ at the top right of the page, or [let us know](doc:getting-help).
