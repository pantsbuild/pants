---
title: "Testimonials"
slug: "testimonials"
excerpt: "Pants is helping many software teams. Here's what some of them have to say."
hidden: false
createdAt: "2021-04-18T19:21:56.778Z"
---
<figure>
 <figcaption>
	<h2>Gordon Cassie</h2>
	<h3>Head of Engineering, Legal Transaction Management</h3>
	<h3><a href="https://imanage.com/">iManage</a></h3>
</figcaption>
<blockquote>
Over the last year at iManage Closing Folders, we transitioned a mature Django monolith with three accompanying microservices to Pants.  Right off the bat, this transition forced us to untangle a convoluted web of dependencies that had emerged in our codebase over the six years it had been actively developed on. Soon after the migration we were able to get significant wins through codesharing between our monolith and microservices.  

Additionally, the safety and speed of our deployment process was drastically augmented by Pants ability to build fully self-contained .pex files. 

For day-to-day work, Pants has empowered developers to create clear separation of concerns between disparate parts of the application, eliminating unnecessary dependencies and improving stability and maintainability.  It has also brought sanity to keeping linting, formatting, third party dependency versioning and python versions consistent across the codebase.  

Compared to other build tools, Pants is drastically more approachable for a small team of python developers, making it possible for an early-stage company to lay the groundwork for a maintainable codebase at an early stage.  Perhaps most importantly, it is backed by a passionate team who are an absolute joy to work with. I would recommend Pants highly to any team!

</blockquote>

**See also Gordon's case study writeup, "[Putting Pants On: One Thing We Did Right After 5 Years with Django](https://g-cassie.github.io/2021/10/02/django-pants.html)"**

</figure>

<figure>
 <figcaption>
	<h2>Alexey Tereshenkov</h2>
	<h3>Software Engineer</h3>
</figcaption>
<blockquote>
We have rolled out Pants across the organization now replacing Conda based workflows. About 75 engineers will be using Pants almost daily via the CI and sometimes locally for REPL and run goal. Pants does magic and the feedback has been hugely positive. I am extending the internal docs as the feedback comes, but nothing major. It's running in CI producing Debian packages and friends, it's pure gold!
</blockquote>
</figure>

<figure>
	<figcaption>
		<h2>Suresh Joshi</h2>
		<h3>Principal Consultant</h3>
		<h3><a href="https://vicarasolutions.com/">Vicara Solutions</a></h3>
	</figcaption>
<blockquote>
<p>I just wanted to write a quick appreciation message for a) Pants itself, and b) all the plugin help I've received <a href="https://www.pantsbuild.org/docs/getting-help">on the Slack community</a>.
<p>I just finished re-writing the entire build/deployment process for a multi-year legacy project using Pants + some custom plugins, and I was able to gut a slapdash set of bash scripts, Dockerfiles, build containers, and who knows what else - in favour of a handful of BUILD files of like 15 lines of code each.
<p>I handed over the project today and this is essentially how it went:
<p><i>Me: "Okay, so to deploy, we have to generate the protobufs, cythonize our core libs, embed the protobufs and core libs in some of our sub-repos, Dockerize the API gateway and microservices, package our system services, and then deploy all of that to our server and then run e2e testing."</i>
<p><i>Client: "Alright, this sounds painful, how do we do it?"</i>
<p><i>Me: "<code>pants deploy :myproject</code>"  [drops keyboard and walks away]</i>
</blockquote>
</figure>

<figure>
	<figcaption>
		<h2>Raúl Cuza</h2>
		<h3>Software Engineer</h3>
		<h3><a href="https://chartbeat.com/">Chartbeat</a></h3>
	</figcaption>
<blockquote>
Pants makes our monorepo keep its promises. In theory, monorepos let any developer make improvements that impact multiple products. Big impact means big responsibility. Pants standardizes the steps, eases discovery, and highlights dependencies, tests, and other projects that are in the improvement impact area. Pants is how we keep do more good than harm with each PR. Pants is also being developed by one of the most helpful open source communities I participate in. They teach and unblock. There can be no higher praise.
</blockquote>
</figure>

<figure>
	<figcaption>
		<h2>Vic Putz</h2>
		<h3>Head of Engineering</h3>
		<h3><a href="https://www.qcware.com/">QC Ware Corp</a></h3>
	</figcaption>
<blockquote>
Moving from "serially building all docker containers with a build script" to "parallel builds using pants": we went from 28.8 minutes (1730 sec) to 611.88 seconds, about a 2.8x improvement! And there's one spectacularly long-build container that's responsible for the long tail; most were built much faster so if it weren't for that laggard this would look even better.

And that's not even counting the impressive dependency checking, etc. that goes with a proper build system.  Very pleased with this.  Thanks for the fantastic support!

</blockquote>
</figure>

<figure>
	<figcaption>
		<h2>Cristian Matache</h2>
		<h3>Software Engineer</h3>
	</figcaption>
<blockquote>
Python is the go-to language for most quants, but its flexibility is a double-edged sword.  While seeing immediate results is great, it is quasi-impossible to tame the code as it grows  large without several external tools: type checkers, linters, formatters, hermetic packers etc.  I love Pants not only because it unifies all these in a few simple and swift commands but also  because it adds hassle-free long-term value. Remember that "time is money", so save some for your future self and add Pants to your repos!
</blockquote>
</figure>

<figure>
	<figcaption>
		<h2>Lukas Haberzettl</h2>
		<h3>Senior Software Developer</h3>
	</figcaption>
<blockquote>
I must say, it’s a life saver. I was impressed with how easy it was to migrate our current projects to Pants. Documentation is well written and the example repos (<a href="https://github.com/pantsbuild/example-python">example-python</a> and  <a href="https://github.com/pantsbuild/example-plugin">example-plugin</a>) are good starting points. Right now we use Pants to manage 5 of our projects and our development process has improved a lot, especially the CI pipeline.
</blockquote>
</figure>

<figure>
	<figcaption>
		<h2>Josh Reed</h2>
		<h3>Senior Site Reliability Engineer</h3>
                <h3><a href="https://aiven.io/">Aiven</a></h3>
	</figcaption>
<blockquote>
Seriously, the level of transparency and communication by Pants team members gives me immense confidence in Pants as a tool, because I have confidence in the team behind it.
</blockquote>
</figure>

<figure>
	<figcaption>
		<h2>Martim Lobao</h2>
		<h3>Data Scientist</h3>
                <h3><a href="https://www.peopledatalabs.com/">People Data Labs</a></h3>
	</figcaption>
<blockquote>
The quality of support we get from Pants open source community is absolutely phenomenal! i don’t think i’ve ever worked with a tool that has such incredible support and development speed.
</blockquote>
</figure>

<figure>
	<figcaption>
		<h2>Robert Grimm</h2>
		<h3>Senior Software Engineer</h3>
                <h3><a href="https://enigma.com/">Enigma</a></h3>
	</figcaption>
<blockquote>
Thank you for answering my questions with so much helpful detail. I much appreciate that. This was actually the first non-employer Slack I ever joined and I'm deeply impressed by your welcoming culture here. I of course consider that another huge plus for the project.
</blockquote>
</figure>

<figure>
	<figcaption>
		<h2>JP Erkelens</h2>
		<h3>Software Engineer</h3>
	</figcaption>
<blockquote>
Pants has been instrumental in democratizing our organization's data platform. It's allowed us to define modern, reliable build processes that can be easily declared from a wide range of personas: from data analysts to software engineers to product managers.
</blockquote>
</figure>
