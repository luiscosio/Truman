import React from 'react';
import {Audio, Composition, Sequence, staticFile} from 'remotion';
import {linearTiming, TransitionSeries} from '@remotion/transitions';
import {fade} from '@remotion/transitions/fade';
import {Blinking, Premise, TwoWorlds} from './scenes/Opening';
import {Build, Layers} from './scenes/Build';
import {Trace} from './scenes/Trace';
import {Answers, Decisive, Missed, Verdict} from './scenes/Verdict';
import {AlsoTested, End, HowItWorks, Lessons, Name, Next, Part, Roadmap, Why} from './scenes/Project';
import {AfterCutoff, Gonggong, History} from './scenes/Later';
import {H, W} from './theme';
// Clip lengths written by narrate.py; a scene without an entry stays silent.
import narration from './narration.json';

const Part1 = () => <Part n="Part 1" title="The project" note="What we’re building and why" />;
const Part2 = () => <Part n="Part 2" title="One experiment, up close" note="Pluto is a planet again, then Gonggong" />;
const Part3 = () => <Part n="Part 3" title="What we learned" note="And where it goes next" />;

// [id, scene, minimum frames]; the id names the scene's narration clip.
const scenes: [string, React.FC, number][] = [
  ['Blinking', Blinking, 260],
  ['Name', Name, 150],
  ['Part1', Part1, 100],
  ['Why', Why, 330],
  ['Roadmap', Roadmap, 300],
  ['HowItWorks', HowItWorks, 420],
  ['Part2', Part2, 100],
  ['Premise', Premise, 250],
  ['TwoWorlds', TwoWorlds, 300],
  ['Build', Build, 300],
  ['Layers', Layers, 330],
  ['Trace', Trace, 450],
  ['Answers', Answers, 270],
  ['Verdict', Verdict, 240],
  ['Decisive', Decisive, 270],
  ['Missed', Missed, 360],
  ['History', History, 330],
  ['AfterCutoff', AfterCutoff, 360],
  ['Gonggong', Gonggong, 390],
  ['Part3', Part3, 100],
  ['Lessons', Lessons, 450],
  ['Next', Next, 300],
  ['AlsoTested', AlsoTested, 480],
  ['End', End, 150],
];

const FPS = 30;
const FADE = 14;
// The voice starts once the fade-in is done and ends before the next fade-out begins.
const LEAD = FADE;
const TAIL = FADE + 16;
const clips: Record<string, {seconds: number}> = narration;
const duration = (id: string, min: number) => {
  const clip = clips[id];
  return clip ? Math.max(min, LEAD + Math.ceil(clip.seconds * FPS) + TAIL) : min;
};
const timed = scenes.map(([id, Scene, min]) => ({id, Scene, frames: duration(id, min)}));
export const total = timed.reduce((sum, s) => sum + s.frames, 0) - FADE * (timed.length - 1);

const Video: React.FC = () => (
  <>
    <style>{'*{box-sizing:border-box}'}</style>
    <TransitionSeries>
      {timed.flatMap(({id, Scene, frames}, i) => [
        ...(i ? [<TransitionSeries.Transition key={`t${i}`} presentation={fade()} timing={linearTiming({durationInFrames: FADE})} />] : []),
        <TransitionSeries.Sequence key={`s${i}`} durationInFrames={frames}>
          <Scene />
          {clips[id] ? (
            <Sequence from={LEAD} layout="none">
              <Audio src={staticFile(`narration/${id}.mp3`)} />
            </Sequence>
          ) : null}
        </TransitionSeries.Sequence>,
      ])}
    </TransitionSeries>
  </>
);

export const RemotionRoot: React.FC = () => <Composition id="TrumanExplainer" component={Video} durationInFrames={total} fps={FPS} width={W} height={H} />;
