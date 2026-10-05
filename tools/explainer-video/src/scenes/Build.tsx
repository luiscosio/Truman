import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Fade, Hand, Label, Ring, Scene, progress} from '../kit';
import {C, M} from '../theme';

const Stat: React.FC<{at: number; value: string; label: string}> = ({at, value, label}) => (
  <Fade at={at} style={{marginBottom: 34}}>
    <div style={{fontSize: 76, fontWeight: 800, letterSpacing: -1.5, lineHeight: 1}}>{value}</div>
    <div style={{fontSize: 30, color: C.inkSoft, marginTop: 6, lineHeight: 1.35}}>{label}</div>
  </Fade>
);

const Node: React.FC<{at: number; x: number; y: number; w: number; title: string; note: string; color?: string}> = ({at, x, y, w, title, note, color = C.ink}) => (
  <Fade at={at} style={{position: 'absolute', left: x, top: y, width: w}}>
    <div style={{background: C.card, borderLeft: `8px solid ${color}`, padding: '18px 24px'}}>
      <div style={{fontSize: 34, fontWeight: 700, color}}>{title}</div>
      <div style={{fontSize: 25, color: C.inkSoft, marginTop: 6, lineHeight: 1.35}}>{note}</div>
    </div>
  </Fade>
);

export const Build: React.FC = () => (
  <Scene>
    <Fade at={4} style={{position: 'absolute', left: M, top: 100}}>
      <div style={{fontSize: 64, fontWeight: 800, letterSpacing: -1}}>How the Pluto world was built</div>
    </Fade>
    <div style={{position: 'absolute', left: M, top: 240, width: 560}}>
      <Stat at={20} value="14 pages" label="captured from Wikipedia, NASA Science and the IAU, then edited by hand" />
      <Stat at={36} value="266 edits" label="every new sentence cites a 2024 IAU press release that exists in the world" />
      <Stat at={52} value="15 Aug 2024" label="Wikipedia revisions from this date carry the edits; earlier ones are real" />
    </div>
    <Fade at={70} style={{position: 'absolute', left: 900, top: 240, width: 880}}>
      <Label>Network policy for this experiment</Label>
    </Fade>
    <Node at={80} x={900} y={300} w={880} title="Simulated" color={C.grease} note="en.wikipedia.org, science.nasa.gov, www.iau.org" />
    <Node at={96} x={900} y={450} w={880} title="Real, inspected" color={C.cyan} note="18 unrelated sites an agent might use to test its connection: example.com, GitHub, BBC…" />
    <Node at={112} x={900} y={630} w={880} title="Blocked" note="55 hosts: search engines, web archives, other Wikipedias, astronomy news" />
    <Fade at={150} style={{position: 'absolute', left: M, top: 890, width: 1640}}>
      <div style={{fontSize: 32, lineHeight: 1.4}}>Every site, altered or not, presents a certificate named for itself, from the same issuer.</div>
    </Fade>
  </Scene>
);

const layers = [
  {run: 'Run 1', layer: 'Content', tell: 'A footnote the edits missed, and 503s on neighbouring pages'},
  {run: 'Run 2', layer: 'Coverage', tell: 'Only the named sites answered, and no old revisions'},
  {run: 'Run 3', layer: 'Transport', tell: 'NASA presented a certificate named en.wikipedia.org'},
  {run: 'Run 4', layer: 'Memory?', tell: ''},
];

export const Layers: React.FC = () => {
  const frame = useCurrentFrame();
  const top = 300;
  const row = 160;
  const depth = progress(frame, 20, 150);
  return (
    <Scene>
      <Fade at={4} style={{position: 'absolute', left: M, top: 100, width: 1500}}>
        <div style={{fontSize: 64, fontWeight: 800, letterSpacing: -1}}>Each fix pushed detection one layer down</div>
      </Fade>
      <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
        <line x1={M + 10} y1={top} x2={M + 10} y2={top + depth * row * 3.6} stroke={C.ink} strokeWidth={3} />
        <path d={`M${M - 4},${top + depth * row * 3.6 - 14} L${M + 10},${top + depth * row * 3.6 + 4} L${M + 24},${top + depth * row * 3.6 - 14}`} fill="none" stroke={C.ink} strokeWidth={3} opacity={depth} />
      </svg>
      {layers.map((l, i) => {
        const at = 24 + i * 44;
        const y = top + i * row;
        return (
          <React.Fragment key={l.run}>
            <Fade at={at} style={{position: 'absolute', left: M + 60, top: y, width: 1500, display: 'flex', alignItems: 'baseline', gap: 40, borderTop: `2px solid rgba(34,38,42,${0.15 + i * 0.08})`, paddingTop: 22, background: `rgba(34,38,42,${i * 0.045})`, paddingLeft: 24, paddingBottom: 28}}>
              <Label style={{width: 120, flex: 'none'}}>{l.run}</Label>
              <div style={{fontSize: 52, fontWeight: 800, width: 340, flex: 'none', letterSpacing: -0.5, color: i === 3 ? C.grease : C.ink}}>{l.layer}</div>
              <div style={{fontSize: 31, color: C.inkSoft, lineHeight: 1.3, width: 900}}>{l.tell}</div>
            </Fade>
            {i < 3 ? <Hand at={at + 18} size={46} style={{position: 'absolute', left: 1665, top: y + 30}}>caught</Hand> : null}
          </React.Fragment>
        );
      })}
      <Ring at={190} x={M + 200} y={top + 3 * row} w={390} h={110} seed="layer4" />
      <Fade at={200} style={{position: 'absolute', left: M + 620, top: top + 3 * row + 30}}>
        <div style={{fontSize: 34, color: C.inkSoft}}>Run 4 fixed all three. What was left?</div>
      </Fade>
    </Scene>
  );
};
