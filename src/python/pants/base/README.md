/src/python/pants/base/

Defines Target and other fundamental pieces/base classes. As a rule of thumb, code in `base`
shouldn't `import` anything in non-base Pants; but many things in non-base Pants `import` from
`base`. If you're editing code in `base` and find yourself referring to the JVM (or other
target-language-specific things), you're probably editing the wrong thing and want to look
further down the inheritance tree.
