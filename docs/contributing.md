# Contributing to FigFox

Collaborate in **LawrenceRiver/FigFox**. Existing collaborators should create a branch in this repository; do not create or push to a fork.

## Commit identity

Use your own verified GitHub commit email for both author and committer. Check `gh api user --jq .login`, `git remote -v`, `git var GIT_AUTHOR_IDENT` and `git var GIT_COMMITTER_IDENT` before committing. Set repository-local `user.name` and `user.email`; do not change someone else's global Git configuration. Do not invent a `.local` email, reuse the owner's email, or attach an unrelated co-author. If the authenticated account or verified email is unclear, resolve it before a commit.

## Workflow

1. Fetch current `main`; create an individual branch from `origin/main`.
2. Edit only the assigned scope. Video: `docs/media.md`, optional thumbnail and the README `FIGFOX:VIDEO` block. Dataset: `docs/figfoxbench.md`, related access-policy text when confirmed, and the README `FIGFOX:BENCH` block.
3. Check links, artifact exclusions and `git diff --check`. Stage exact paths; do not use a broad add that includes local outputs.
4. Verify your author/committer email, commit, and push the branch to `origin` in the original repository.
5. Open a PR to `LawrenceRiver/FigFox:main`. Preserve the original author commits when merging; do not rewrite published history or force push `main`.

Only meaningful changes should be committed. GitHub controls contributor indexing; a PR alone does not guarantee immediate sidebar credit. Own-authored changes merged into the default branch with a linked email are the appropriate basis for attribution. Keep the visible contributor credit accurate without inventing work or synthetic attribution commits.

Raw run outputs, logs, provider replies, private benchmark images, credentials, weights and large videos are outside the Git source tree. Update to the latest `main` before editing a shared README, and preserve the other contributor's markers and changes.
