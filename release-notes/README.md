# Release notes

One file per version, named after it: `release-notes/1.0.24.md` for v1.0.24.
Write it before you push the tag.

The Release workflow (`scripts/release-body.ps1`) puts this file at the top of
the GitHub release page. Admin > Updates shows it under "What's new" to
someone deciding whether to update, and shows nothing else from the page: the
"Which file do I need?" download guide and GitHub's change list stay on the
release page only. If the file is missing the release still publishes, with a
line saying no notes were written.

## How to write one

- A few bullets, one per change a person would notice. Cover everything since
  the last release, including versions in between that had no notes file.
- Plain language, from the user's side: what they can now do, what stopped
  going wrong, anything they have to do. "Setup no longer hangs when started
  by winget", not "fix(setup): drop winget fallback in install.ps1".
- No commit hashes, PR numbers, branch names, file names or code terms.
- Leave out changes nobody using F7FIVE0 would notice (tests, CI, refactors,
  docs for developers). A security fix gets one line saying so.
- Markdown is fine: bullets, **bold**, `code`, [links](https://example.com),
  short headings. Keep tables out; the Updates box is small.
- Don't paste the line `<!-- f7five0:download-guide -->`; the workflow adds it.

Preview the release page text before tagging:

```
pwsh scripts/release-body.ps1 -Version 1.0.24 -OutFile notes-preview.md
```
