# Build log

NextStep Hacks scores "learning and skill growth" as a published judging
criterion, which is unusual. This file is the record for it: what was decided,
what was got wrong, and what was learned. Newest entries at the bottom.

---

## 6 September 2026 — Day 0

**Decided the project.** Chose a pollution complaint agent over an agricultural
advisory agent. Both fit the environmental theme, but the Agents for Humans brief
is specifically about automating repetitive work, and an advisory chatbot reads as
a chatbot. Filing and chasing a regulatory complaint is genuinely tedious,
genuinely repetitive, and genuinely something almost nobody completes.

**Verified the multi-hackathon plan before writing code.** Fetched both rules
pages. Neither NextStep nor Agents for Humans contains an exclusivity clause, and
the Agents for Humans submission window opened 10 August, so a build starting
6 September is inside it. This was worth checking first; the whole plan rests on
it.

**Confirmed the Strands SDK ships a first-party Gemini provider.** This is what
keeps a Google-hosted submission possible later without a rewrite, and it is why
`models.build_model()` exists as the only place a provider is constructed.

**Read the SDK API rather than assuming it.** Checked the installed package
directly for the image content block shape and the `Agent.__call__` signature
instead of guessing from memory. Two things would have been wrong: structured
output is now a `structured_output_model` parameter on the call, not the
deprecated `Agent.structured_output()` method; and image blocks are Bedrock-shaped
(`{"image": {"format": ..., "source": {"bytes": ...}}}`).

**Designed the graph to match the problem, not the marketing.** The first instinct
was to make the whole pipeline a `GraphBuilder` graph because multi-agent graphs
are the SDK's headline feature. That would have been decoration: classification
must precede corroboration, and jurisdiction must precede drafting, so those are
real dependencies. The one genuine fan-out is corroboration, where satellite,
ground station, and meteorology are independent. Only that stage is a graph.

**Made filing safety a tested property, not a note in the README.** The obvious
failure mode for this project is emailing a real pollution control board from a
demo. So: live filing raises rather than sends, every committed authority email is
on the reserved `.invalid` TLD, and there is a test that walks the JSON and
asserts it.
