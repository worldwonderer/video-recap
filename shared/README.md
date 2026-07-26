# shared/ — source of truth for code copied into skills

Skills in this bundle are self-contained: a skill's scripts may only import that skill's
own modules, and the stages communicate solely through `work_dir` artifacts. That rule is
enforced by `tests/orchestrator/test_test_suite_architecture.py` and it is deliberate — a
stage can be run, tested, and reasoned about on its own.

Self-contained does not mean each copy must be written by hand. The files here are the
single source; `scripts/sync_shared.py` copies them into each skill that needs them, with
a `GENERATED FILE` banner. Runtime is unchanged: every skill still imports only its own
local modules.

```sh
python scripts/sync_shared.py           # edit shared/, then distribute
python scripts/sync_shared.py --check    # verify (also asserted by pytest and CI)
```

**Never edit a generated copy.** The next sync overwrites it, and the anti-drift test
fails in the meantime. Edit the file here instead.

## What lives here, and why it is shared rather than owned

| source | copied into | why |
| --- | --- | --- |
| `fingerprint.py` | all six skills | Digests are compared *across* skills: video-cut writes `edited_source.mp4.meta.json`, video-recap and video-assemble read it back. A divergence turns into cache misses or false cache hits. |
| `agent_brief.py`, `agent_text.py`, `brief_context.py`, `brief_inputs.py`, `brief_timeline.py`, `timeline_fusion.py`, `speech_ownership.py` | video-understanding, video-script | video-understanding produces the writing brief; video-script validates narration against the same facts. The two must derive them identically. |
| `narration_lint.py`, `deslop_qc.py` | video-understanding, video-script | Same lint has to give the same verdict at authoring time and at validation time. |
| `brief_entry.py` | `video-understanding/scripts/brief.py`, `video-script/scripts/narration.py` | One module, exposed under each skill's own public name. |
| `creative-editing-playbook.md` | video-recap, video-script | The orchestrator and the writing skill hand the agent the same playbook. |

## What does NOT belong here

Configuration. Each skill's `lib.py` declares only the knobs its own code reads —
`tests/orchestrator/test_audio_policy_parity.py` asserts that no skill declares config
nothing in it reads. Copying a shared `CONFIG` into every skill is what produced 583 dead
declarations, a `CLIP_PADDING` knob that did nothing in the one skill that implements
padding, and a `zone_fade_seconds` that no code anywhere read.
