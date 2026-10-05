# Explainer video

A four-minute silent video that explains Truman with one worked example, the
[Pluto experiment](../../experiments/pluto-planet-20261001/README.md). Part 1 covers
what the project is for and what has been tested so far; part 2 follows one
experiment, including the [post-cutoff variant](../../experiments/pluto-planet-after-cutoff-20261005/README.md) and the [Gonggong world](../../experiments/gonggong-dwarf-planet-20261005/README.md) that passed; part 3 covers what it suggests about simulation awareness and what is next.

It is a [Remotion](https://www.remotion.dev/) project. Every number, quotation and
request shown comes from the experiment write-ups and sealed run records; the run 4
timeline in `src/scenes/Trace.tsx` uses event times read from the two `run.json` files.
Update the scenes by hand when the write-ups change.

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
