import React from 'react';
import {Composition} from 'remotion';
import {linearTiming, TransitionSeries} from '@remotion/transitions';
import {fade} from '@remotion/transitions/fade';
import {Blinking, Premise, TwoWorlds} from './scenes/Opening';
import {Build, Layers} from './scenes/Build';
import {Trace} from './scenes/Trace';
import {Answers, Decisive, Missed, Verdict} from './scenes/Verdict';
import {End, HowItWorks, Lessons, Name, Next, Part, Roadmap, SoFar, Why} from './scenes/Project';
import {H, W} from './theme';

const Part1 = () => <Part n="Part 1" title="The project" note="What we’re building and why" />;
const Part2 = () => <Part n="Part 2" title="One experiment, up close" note="Pluto is a planet again" />;
const Part3 = () => <Part n="Part 3" title="What we learned" note="And where it goes next" />;

const scenes: [React.FC, number][] = [
  [Blinking, 260],
  [Name, 150],
  [Part1, 100],
  [Why, 330],
  [Roadmap, 300],
  [HowItWorks, 420],
  [SoFar, 600],
  [Part2, 100],
  [Premise, 250],
  [TwoWorlds, 300],
  [Build, 300],
  [Layers, 300],
  [Trace, 450],
  [Answers, 270],
  [Verdict, 240],
  [Decisive, 270],
  [Missed, 360],
  [Part3, 100],
  [Lessons, 450],
  [Next, 300],
  [End, 150],
];

const FADE = 14;
export const total = scenes.reduce((sum, [, d]) => sum + d, 0) - FADE * (scenes.length - 1);

const Video: React.FC = () => (
  <>
    <style>{'*{box-sizing:border-box}'}</style>
    <TransitionSeries>
      {scenes.flatMap(([Scene, d], i) => [
        ...(i ? [<TransitionSeries.Transition key={`t${i}`} presentation={fade()} timing={linearTiming({durationInFrames: FADE})} />] : []),
        <TransitionSeries.Sequence key={`s${i}`} durationInFrames={d}>
          <Scene />
        </TransitionSeries.Sequence>,
      ])}
    </TransitionSeries>
  </>
);

export const RemotionRoot: React.FC = () => <Composition id="TrumanExplainer" component={Video} durationInFrames={total} fps={30} width={W} height={H} />;
