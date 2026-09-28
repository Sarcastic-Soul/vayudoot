# Running agents in parallel

Coordination rules for splitting work across concurrent agents. Referenced from CLAUDE.md.

Independent work should be split across agents rather than done in sequence. It
is materially faster, and the constraint that makes it work is file ownership,
not task size.

**One owner per file, per wave.** Two agents editing `api.py` at once produces a
merge, not a speedup. Partition by the files a task must touch, and if two tasks
want the same file, they belong in the same agent or in different waves. The
usual clean split is Python versus `src/vayudoot/web`, since the interface and
the pipeline share nothing.

**Keep shared documents out of every brief.** `CLAUDE.md`, `docs/SCOPE.md` and
`README.md` are written by whoever is coordinating. Several agents editing the
same document concurrently is the one conflict that is guaranteed.

**Agents do not commit.** They leave the work in the tree and report. The
coordinator reads the diff, verifies it independently, and commits — an agent
reporting success is evidence, not proof.

Tell each agent: which paths it owns and which it must not touch; that another
agent is working concurrently, so a test failure in a file it did not touch is
not its problem; and that a dev server it starts is its own to stop, because a
stray one holds the port for everybody afterwards.

For interface work, require rendered screenshots. Every UI bug in this project
so far — invisible nav labels, a clipped control, a single-column layout that
should have been two — passed both `ruff` and `pytest` and was only ever visible
in an image.

