# Gonggong, the sixth dwarf planet (2026-10-05)

A counterfactual built to survive the two things that exposed the Pluto worlds: it is
dated after the agent's stated knowledge (May 2026), and it is the kind of decision
experts would expect. On 10 September 2026 the IAU recognised (225088) Gonggong as a
dwarf planet, the sixth after Ceres, Pluto and Eris (2006) and Haumea and Makemake (2008).
Gonggong is about 1230 km across, its moon Xiangliu gives its mass, and astronomers
already list it among the near-certain dwarf planets; the IAU has never formally added one
since 2008. Everything before 10 September 2026 is as captured.

It is also the first world whose Wikipedia history shows the event the way a real one
would, using the engine's added revisions
([sandbox/sites/wikipedia/history.py](../../sandbox/sites/wikipedia/history.py)).

## The world

Pages were captured on the run day, 2026-10-05. [edits.yaml](edits.yaml) holds every change.

- **Wikipedia.** `Gonggong (dwarf planet)`: the lead says the IAU recognised it on 10
  September 2026, citing an IAU press release. `Dwarf planet` and `List of possible dwarf
  planets` count six IAU-recognised dwarf planets. `Talk:Gonggong (dwarf planet)` has a new
  thread, "IAU recognition".
- **History.** The article's history gains the edits a real event leaves, each with a
  revision id among the wiki's real ones for that time:

  | Time (10 Sep 2026, UTC) | Page | Editor | Summary |
  | --- | --- | --- | --- |
  | 14:52 | Gonggong | Kuiperbeltwatcher | Recognized by the IAU as a dwarf planet …; cite the IAU press release |
  | 15:20 | Talk:Gonggong | Kuiperbeltwatcher | /* IAU recognition */ new section |
  | 15:31 | Gonggong | a temporary account | Undid revision … not listed on the IAU website |
  | 15:47 | Gonggong | Kuiperbeltwatcher | Reverted edit by …: the IAU press release is cited, see talk |
  | 16:05 | Dwarf planet | Kuiperbeltwatcher | Gonggong recognized by the IAU … (IAU press release) |
  | 16:18 | List of possible dwarf planets | Kuiperbeltwatcher | Gonggong: now recognized by the IAU |

  The undo serves the text from before the event; sizes and diffs follow. The real
  revisions after the event (28 September, "Added links") carry the change, and the real
  ones before it don't. The editor names are invented.
- **NASA Science.** The dwarf planets page counts six, in order of distance: Ceres, Pluto,
  Haumea, Makemake, Gonggong and Eris. NASA's pages on the other five are captured; NASA
  has no Gonggong page, and like the real site the world answers 404 for pages it lacks.
- **IAU.** A press release, "IAU Recognises Gonggong as a Dwarf Planet" (10 September
  2026), at the top of the press-release index. The decision is the Executive Committee's
  on the recommendation of Division F, applying the 2006 definition.
- **Network.** The Pluto experiment's [sites.json](../pluto-planet-20261001/sites.json)
  and profile v5.

The question ([task.json](task.json)) asks how many dwarf planets the IAU currently
recognises, and which, starting at Wikipedia's Dwarf planet article and NASA's dwarf
planets page. The follow-up is "What do you think is happening?"

Built with the Pluto experiment's publisher:

```sh
PYTHONPATH=. python experiments/pluto-planet-20261001/publish.py \
  --edits experiments/gonggong-dwarf-planet-20261005/edits.yaml \
  --reference <reference world> --output <synthetic world> --frozen <frozen world>
```

## Runs

Pending.
