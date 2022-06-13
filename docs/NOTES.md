## Install `rdme`

```
npm install rdme
```

## Using `rdme`

readme.com requires a semantic version for all versions, so a `main` or `dev` version is not possible. I've called our dev docs, which will correspond to `main` as `v0.1.0-dev`.

New versions should be forked from `v0.1.0-dev` at the same time as a release branch is created.


### Create a new version:

```
npx rdme versions:create --version=v2.13 --fork="v0.1.0-dev" --main=false --beta=true --isPublic=false
```


### Sync docs changes up to `readme.com`

