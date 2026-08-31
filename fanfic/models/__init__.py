"""The propose half of propose/dispose — and the ONLY layer that reaches a model.

Three modules, one contract: a model call always names an output path in its prompt
and we read that *file*. Never stdout. Both sibling repos learned this the hard
way; a model that streams beautifully but never writes the file has failed, full
stop, and stdout is kept only for a short rationale in the decisions log.

  * `prompts` — assemble a runtime prompt from a committed template plus this job's
                facts plus the write-to-exactly-this-path instruction.
  * `text`    — the one seam for all prose and judgment. Resolves whichever
                provider is configured; see `fanfic/providers/`.
  * `images`  — the HTTPS seam for all image generation.

Every entry point here is a thin named function so a test can monkeypatch one seam
and drive the entire harness on fixtures. Nothing in this layer has the authority
to mutate committed state: it returns proposals, and the caller validates them.
"""
