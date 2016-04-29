How To Ask
==========

Sometimes you have a question about Pants' behavior. Sometimes you want
to report a Pants bug. You want to tell other people about something
strange that Pants is doing. Since those people can't look over your
shoulder, you must provide details about your environment and Pants'
behavior.

-   What command[s] did you enter?
-   What was the output?
-   What output did you expect instead?
-   If you are on the `pantsbuild/pants` git repo, what is your branch
    and sha? Please report the output of these commands:

        :::bash
        $ git branch
        $ git log -1

-   If you're on your own branch, push it to origin so that other
    people can see it and perhaps try to reproduce the behavior. (If
    you're using `pantsbuild/pants` itself and don't have permission
    to push to that repo, you might need to clone the repo first.)
    Please report the branch's location, as shown by the output of
    these commands (where myusername\_myproblem is a branch name you
    choose):

        :::bash
        $ git push origin myusername_myproblem
        $ git remote -v | grep origin

**Post this information** as a new thread on the [pants-devel Google
Group](https://groups.google.com/forum/#!forum/pants-devel)

