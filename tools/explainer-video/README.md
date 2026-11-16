# Explainer video

A five-minute narrated video that explains Truman with one worked example, the
[Pluto experiment](../../experiments/pluto-planet-20261001/README.md). Part 1 covers
what the project is for and how it works; part 2 follows one
experiment, including the [post-cutoff variant](../../experiments/pluto-planet-after-cutoff-20261005/README.md) and the [Gonggong world](../../experiments/gonggong-dwarf-planet-20261005/README.md) that passed; part 3 covers what it suggests about simulation awareness and what is next.

It is a [Remotion](https://www.remotion.dev/) project. Every number, quotation and
request shown comes from the experiment write-ups and sealed run records; the run 4
timeline in `src/scenes/Trace.tsx` uses event times read from the two `run.json` files.
Update the scenes by hand when the write-ups change.

## Narration

The voice-over is the author's own ElevenLabs voice, one clip per scene. `narration/script.json`
holds the lines; `narrate.py` synthesizes them into `public/narration/` and writes each
clip's length to `src/narration.json`. `Root.tsx` stretches a scene to fit its clip (never
shorter than the scene's own minimum) and plays the clip once the fade-in is done. The
clips are committed, so rendering needs no ElevenLabs account; only changing a line does:

```sh
uv run python tools/explainer-video/narrate.py          # from the repository root
uv run python tools/explainer-video/narrate.py Gonggong # redo one scene
```

It reads `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` from the environment or the
Git-ignored `.env`, and skips clips whose text, model and voice haven't changed.

## Render

Install and render from the runtime checkout, outside Dropbox, so `node_modules`
(about 400 MB) and renders don't sync. Both are ignored by Git.

```sh
cd ~/.local/share/truman/mac/tools/explainer-video
pnpm install
pnpm typecheck
pnpm render            # out/truman-explainer.mp4, 1080p30, about 15 minutes
node stills.mjs 240 1064 2950   # half-size frames in out/stills, to check layout
```

The first render downloads Chrome Headless Shell (about 90 MB). The esbuild install
script is skipped on purpose; the package works without it.

## Layout

| File | Contents |
| --- | --- |
| `src/Root.tsx` | Scene order, durations and crossfades |
| `src/theme.ts` | Palette and fonts |
| `src/kit.tsx` | Plate background, grease-pencil marks, text reveals |
| `src/scenes/Project.tsx` | Parts 1 and 3: goals, roadmap, architecture, history, lessons |
| `src/scenes/Opening.tsx`, `Build.tsx`, `Trace.tsx`, `Verdict.tsx`, `Later.tsx` | Part 2: the Pluto experiment (runs 1 to 5, the post-cutoff variant) and Gonggong |

The look borrows from Clyde Tombaugh's 1930 discovery plates: two photographs of the
same sky, compared to find what moved. Red handwriting marks findings, as astronomers
marked plates.
