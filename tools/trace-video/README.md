# Captioned trajectory videos

Create a 1080p MP4 from a saved Truman run. **Abstract mode** produces a fast animated
sequence with brief paraphrased reactions, an agent icon, moving page cards and a
short answer with its caveat. Walkthrough mode retains the complete final response
on screen. Both use recorded-page screenshots. The exporter also writes a local video
player with chapter buttons, a storyboard with event IDs, captions, the original
final-response Markdown and the recorded events. A VP9 WebM copy supports embedded
browsers that cannot decode H.264; the player prefers that copy.

The implementation uses Python/Pillow for caption cards, an isolated headless
Chromium renderer for screenshots and FFmpeg for encoding. No Remotion project,
provider key or rewriting model is needed. The default output is silent.

## Short animated version

```sh
NODE_PATH=/path/to/external/video-deps/node_modules \
PYTHONDONTWRITEBYTECODE=1 python tools/trace-video/trace_video.py \
  /path/to/runs/my-recorded-run --output /path/to/reports/my-short-video \
  --style abstract --story /path/to/my-short-story.json
```

Use [the 52-second example](../../examples/manual-monarchy-20260919/video-short-story.json)
as a starting point. Each beat has a kind, a short `text`, duration and source event
IDs. Supported kinds are `question`, `fetch`, `reaction`, `pair`, `agreement`,
`conflict`, `answer`, `intro` and `verdict`. Page cards reference automatically grouped scene keys
(`call-3`, for example) and supply short display labels and findings. The `answer`
beat includes a separate `caveat` that appears after the initial answer.

Start with the user's question. An optional `intro` beat adds a `brand`, research
question and short `subtext`. A `verdict` beat adds a red outcome card with
`subtext`; link it to the recorded evidence, and distinguish suspicion from proof.
The character is explicitly labeled as an AI agent. Keep each reaction to a few words and tie it to
visible actions or statements in the recording. Paraphrases are explicitly labeled;
do not present them as literal thoughts or quotations. The short story is authored
by the operator, not inferred by a hidden summarization model. The original full
response remains available as a download and is not shown in this mode.

## Install and run

Use a virtual environment outside Dropbox, as with the main Mac runtime. Install
Pillow in that environment and FFmpeg on the machine. Install Node.js, Playwright
and its Chromium browser in an external dependency directory:

```sh
python -m pip install Pillow
npm install --prefix /path/to/external/video-deps playwright
/path/to/external/video-deps/node_modules/.bin/playwright install chromium
```

From the repository root:

```sh
NODE_PATH=/path/to/external/video-deps/node_modules \
PYTHONDONTWRITEBYTECODE=1 python tools/trace-video/trace_video.py \
  /path/to/runs/my-recorded-run \
  --output /path/to/reports/my-trajectory-video
```

The output directory must be new. Start (or restart) the updated local report
viewer with `python -m truman serve --directory /path/to/reports`, then open
`http://127.0.0.1:8765/my-trajectory-video/index.html`. The viewer serves the video
assets and supports seeking. Alternatively, play `trajectory.mp4` directly.
The MP4 contains chapter markers and no
audio track. Fonts use Arial on macOS/Windows or DejaVu Sans on Linux.

For the manually prepared monarchy run, add:

```sh
--story examples/manual-monarchy-20260919/video-story.json
```

The source run must contain `run.json` and its original response blobs. Image
resources must also be present in the recording/world snapshot. Nothing is fetched
from live websites. Missing response blobs fail explicitly rather than replacing
the evidence with a current page.

## Editing the story

Use `--plan-only` with a new output directory to list scene keys and grouped event
IDs. A story file maps those keys to `title`, `caption`, `duration` (seconds),
`selector` (an optional CSS scroll target), `eyebrow`, `footer` or `skip`. Example:

```json
{
  "title": "A source-checking walkthrough",
  "scenes": {
    "call-3": {
      "title": "Open the starting page",
      "caption": "The page loads. Its introduction gives the following answer…",
      "duration": 15
    }
  }
}
```

Use `after` for clearly labeled editorial notes. Captions are operator-authored
explanations, not additional evidence. The exporter rejects changes to the source
event fields or final-response scene. The complete answer is paginated rather than
summarized; Markdown styling and link destinations are omitted from the on-screen
plain text, while `final-response.md` retains the original verbatim Markdown.

`--frames-only` renders the screenshots and caption cards for inspection without
encoding. `--wpm` controls default reading time (170 words/minute); explicit scene
durations override it. Long intermediate tool output is excerpted on screen and
retained in the transcript. Non-HTML responses and unavailable pages are shown as
text, never as invented website screenshots. Failures remain visible in the plan
and outcome; request grouping does not convert a failed request into a success.

Concurrent fetches are linked by call identity and requested URL, not by adjacency.
Ambiguous network events remain separate steps. Sequential presentation of concurrent
reads is an explanatory choice; it does not claim the agent waited between them.

## Evidence and limits

These are offline re-rendered screenshots of recorded HTML, not a recording of an
agent operating a visual browser. Scripts/service workers and all unrecorded
network requests are disabled in the renderer. The renderer uses captured resource
URLs and Truman's content-addressed assets. Missing external styling/media can
affect appearance; `page-renders.json` lists every blocked request and the source
HTML hash. The source run is never modified.

The current end-to-end test is the Wikipedia fixture. The exporter does not add
website adapters or establish cross-site world consistency. Other recorded HTML
can be rendered, but different site layouts may need a story-specific scroll
selector and visual review. This is a review video, not an inference-time benchmark;
reading times are expanded for viewers.

The local player and sidecars retain the run's prompts, tool output and references.
Treat that bundle with the same sharing permissions as the original recording.

Implementation references: [Playwright screenshot API](https://playwright.dev/python/docs/screenshots)
and [FFmpeg documentation](https://www.ffmpeg.org/ffmpeg.html).

Run the focused grouping/integrity tests with:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -p test_trace_video.py
```
