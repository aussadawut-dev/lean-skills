<!--
Release notes template. Copy everything below this comment into the GitHub release body.

How to write it:
- Speak to the reader as "you". Short sentences, one idea each.
- Order every section by what the user gains, not by the order the work happened.
- State what was verified and what was not, in separate sections. Never merge them.
- Use only facts from the merged PRs and CI runs. Write "none" rather than leaving a section out.
- Keep skill names, commands, flags and labels (DONE, BLOCKED, FAILED) exactly as they ship.
- Title the release "Lean Skills vX.Y.Z".
-->

<!-- One sentence: the single most important change, in the user's terms. -->
<summary sentence>

## What's new

<!-- One bullet per change the user can notice. Bold lead word, then what it does for them. -->
- **<Lead word>.** <What changed, and what you can now do.>
- **<Lead word>.** <What changed, and what you can now do.>

## Upgrade

<!-- The command to run, then anything the user must change by hand. Write "Nothing else to change." when that is true. -->
Update the installed skills in the scope you installed them (add `-g` for global):

```sh
npx skills add aussadawut-dev/lean-skills --skill '*' -a codex claude-code antigravity -y
```

To keep local edits, use `lean-update` instead.

<Manual changes, or "Nothing else to change.">

## Verified

<!-- What actually ran, where, and the result. Name the host and counts. -->
- <Check>: <result>.

## Not verified

<!-- What this release does not establish. Write "None." only if every claim above was exercised. -->
- <Gap>.

## Links

- [Pull request #<n>](https://github.com/aussadawut-dev/lean-skills/pull/<n>)
