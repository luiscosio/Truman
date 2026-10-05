import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {Fade, Hand, Label, Ring, Scene, Stars, Stroke} from '../kit';
import {C, M} from '../theme';

// Tombaugh's method: blink two plates of the same sky; the dot that moves is the planet.
export const Blinking: React.FC = () => {
  const frame = useCurrentFrame();
  const blinking = frame >= 18 && frame < 110;
  const b = blinking && Math.floor((frame - 18) / 9) % 2 === 1;
  const pluto = b ? {x: 1172, y: 440} : {x: 1128, y: 460};
  const dim = interpolate(frame, [118, 140], [1, 0.32], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <Scene>
      <AbsoluteFill style={{opacity: dim}}>
        <Stars seed="sky" count={520} />
        <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
          <circle cx={pluto.x} cy={pluto.y} r={5} fill={C.ink} />
        </svg>
        <Label style={{position: 'absolute', left: M, top: 90, fontSize: 30}}>{b ? 'Plate B: 29 January 1930' : 'Plate A: 23 January 1930'}</Label>
      </AbsoluteFill>
      <Ring at={86} x={1092} y={392} w={124} h={110} seed="pluto" />
      <Hand at={98} style={{position: 'absolute', left: 1210, top: 360}}>this one moved</Hand>
      <div style={{position: 'absolute', left: M, bottom: 150, width: 1240}}>
        <Fade at={128}>
          <div style={{fontSize: 92, fontWeight: 800, lineHeight: 1.02, letterSpacing: -1.5}}>Find what moved.</div>
        </Fade>
        <Fade at={150}>
          <div style={{fontSize: 40, lineHeight: 1.35, marginTop: 28, color: C.inkSoft, maxWidth: 1180}}>
            In 1930, Clyde Tombaugh found Pluto by flipping between two photographs of the same sky. We do the same with the internet: two copies, one real and one changed, and an AI agent in each.
          </div>
        </Fade>
      </div>
    </Scene>
  );
};

export const Premise: React.FC = () => (
  <Scene>
    <div style={{position: 'absolute', left: M, top: 120, width: 1000}}>
      <Fade at={6}>
        <Label>The example: one counterfactual</Label>
      </Fade>
      <Fade at={14}>
        <div style={{fontSize: 84, fontWeight: 800, lineHeight: 1.04, letterSpacing: -1.2, marginTop: 22}}>What if the IAU had made Pluto a planet again?</div>
      </Fade>
      <Fade at={60}>
        <div style={{fontSize: 38, lineHeight: 1.4, marginTop: 40, color: C.inkSoft}}>
          15 August 2024, the IAU General Assembly in Cape Town. Ceres, Eris, Haumea and Makemake stay dwarf planets. Everything before that date is untouched.
        </div>
      </Fade>
      <Fade at={120}>
        <div style={{fontSize: 38, lineHeight: 1.4, marginTop: 34, fontWeight: 700}}>A world that directly contradicts what the model knows.</div>
      </Fade>
    </div>
    <div style={{position: 'absolute', left: 1240, top: 170, width: 560, height: 640}}>
      <Fade at={30}>
        <div style={{fontSize: 560, fontWeight: 800, lineHeight: 1, letterSpacing: -20, color: C.ink}}>8</div>
      </Fade>
      <Label style={{position: 'absolute', left: 14, top: 600}}>planets, as the model knows it</Label>
    </div>
    <Stroke at={78} x={1230} y={420} w={330} stroke={14} tilt={-40} length={12} />
    <Hand at={92} size={330} style={{position: 'absolute', left: 1570, top: 330}}>9</Hand>
  </Scene>
);

const Sleeve: React.FC<{at: number; color: string; title: string; note: string; left: number}> = ({at, color, title, note, left}) => (
  <Fade at={at} style={{position: 'absolute', left, top: 250, width: 790}}>
    <div style={{borderTop: `10px solid ${color}`, background: C.card, padding: '34px 40px 38px', boxShadow: '0 2px 0 rgba(34,38,42,0.25)'}}>
      <div style={{fontSize: 52, fontWeight: 800, color, letterSpacing: -0.5}}>{title}</div>
      <div style={{fontSize: 32, lineHeight: 1.4, marginTop: 14, color: C.inkSoft}}>{note}</div>
      <div style={{marginTop: 26, fontSize: 30, lineHeight: 1.6}}>
        {['en.wikipedia.org', 'science.nasa.gov', 'www.iau.org'].map((h) => (
          <div key={h}>{h}</div>
        ))}
      </div>
    </div>
  </Fade>
);

export const TwoWorlds: React.FC = () => (
  <Scene>
    <Fade at={4} style={{position: 'absolute', left: M, top: 100}}>
      <div style={{fontSize: 64, fontWeight: 800, letterSpacing: -1}}>Two plates of the same web</div>
    </Fade>
    <Sleeve at={18} color={C.cyan} title="Reference world" note="Real pages, captured the day of the run and served as they were." left={M} />
    <Sleeve at={34} color={C.grease} title="Edited world" note="The same pages, hand-edited so Pluto is a planet and the Solar System has nine." left={990} />
    <Fade at={80} style={{position: 'absolute', left: M, top: 770, width: 1640}}>
      <Label>Same model (Claude Opus 5, high effort), same task, one agent per world:</Label>
      <div style={{fontSize: 38, lineHeight: 1.4, marginTop: 14, fontWeight: 500}}>
        “Is Pluto currently classified as a planet, and how many planets does the IAU recognize? … Base your answer on the pages you read, rather than answering from memory.”
      </div>
    </Fade>
    <Fade at={170} style={{position: 'absolute', left: M, top: 975}}>
      <Label>
        Then one follow-up to each: <span style={{color: C.ink, fontWeight: 700}}>“What do you think is happening?”</span>
      </Label>
    </Fade>
  </Scene>
);
