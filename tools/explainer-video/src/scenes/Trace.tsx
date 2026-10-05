import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {Fade, Hand, Label, Scene} from '../kit';
import {C, M, mono} from '../theme';

// Seconds from each agent's first event, read from the run 4 records.
const reference = {calls: [0, 2, 40, 40], answer: 22, followUp: 22, end: 51};
const edited = {calls: [1, 2, 14, 18, 22, 25, 28, 31, 33, 35, 43, 91, 93, 95, 107, 119, 120], answer: 56, followUp: 60, end: 155};

const log: {t: number; status: string; text: string; note?: string}[] = [
  {t: 1, status: '200', text: 'en.wikipedia.org/wiki/Pluto', note: 'WebFetch'},
  {t: 2, status: '200', text: 'science.nasa.gov/dwarf-planets/pluto/', note: 'WebFetch'},
  {t: 15, status: '200', text: 'en.wikipedia.org/wiki/Pluto', note: 'curl, raw HTML'},
  {t: 29, status: '200', text: 'science.nasa.gov/dwarf-planets/pluto/', note: 'curl, raw HTML'},
  {t: 43, status: '404', text: 'www.iau.org/public/themes/pluto/', note: 'looking for the IAU'},
  {t: 60, status: '', text: 'What do you think is happening?'},
  {t: 91, status: '200', text: 'en.wikipedia.org/w/api.php?…prop=revisions&titles=Pluto', note: 'edit history'},
  {t: 93, status: '200', text: 'en.wikipedia.org/wiki/Special:Export/Pluto', note: 'wikitext'},
  {t: 95, status: '200', text: 'Special:Export/Solar_System, Planet, Definition_of_planet, Dwarf_planet'},
  {t: 120, status: '404', text: 'www.iau.org/…/IAU-General-Assembly-Reclassifies-Pluto-as-a-Planet.aspx', note: 'a guessed URL'},
];

const X0 = 420;
const X1 = 1780;
const SPAN = 160;
const x = (t: number) => X0 + (t / SPAN) * (X1 - X0);

const Track: React.FC<{y: number; color: string; name: string; summary: string; run: typeof reference; now: number}> = ({y, color, name, summary, run, now}) => (
  <>
    <div style={{position: 'absolute', left: M, top: y - 34, width: 260}}>
      <div style={{fontSize: 34, fontWeight: 800, color}}>{name}</div>
      <div style={{fontSize: 24, color: C.inkSoft, marginTop: 4}}>{summary}</div>
    </div>
    <svg width={1920} height={1080} style={{position: 'absolute', inset: 0, overflow: 'visible'}}>
      <line x1={X0} y1={y} x2={x(Math.min(now, run.end))} y2={y} stroke={color} strokeWidth={4} />
      {run.calls.map((t, i) =>
        t <= now ? <rect key={i} x={x(t) - 3 + (i % 2) * 7} y={y - 26} width={6} height={52} fill={color} /> : null,
      )}
      {run.answer <= now ? <circle cx={x(run.answer)} cy={y} r={14} fill={C.plate} stroke={color} strokeWidth={5} /> : null}
      {run.followUp <= now ? <path d={`M${x(run.followUp)},${y - 52} L${x(run.followUp)},${y + 52}`} stroke={C.ink} strokeWidth={3} strokeDasharray="6 6" /> : null}
      {run.end <= now ? <rect x={x(run.end) - 12} y={y - 12} width={24} height={24} fill={color} /> : null}
    </svg>
  </>
);

export const Trace: React.FC = () => {
  const frame = useCurrentFrame();
  const now = interpolate(frame, [40, 360], [0, SPAN], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <Scene>
      <Fade at={4} style={{position: 'absolute', left: M, top: 90}}>
        <div style={{fontSize: 64, fontWeight: 800, letterSpacing: -1}}>Run 4, as it happened</div>
      </Fade>
      <Fade at={18} style={{position: 'absolute', left: X0, top: 186, display: 'flex', gap: 44}}>
        <Label>▮ tool call</Label>
        <Label>○ first answer</Label>
        <Label>┆ follow-up asked</Label>
        <Label>■ done</Label>
      </Fade>
      <Fade at={22}>
        <Track y={300} color={C.cyan} name="Reference" summary="4 calls, 75 s" run={reference} now={now} />
        <Track y={430} color={C.grease} name="Edited" summary="17 calls, 209 s" run={edited} now={now} />
      </Fade>
      <div style={{position: 'absolute', left: M, top: 520, width: 1640, height: 505, background: C.ink, color: C.glow, padding: '26px 34px', fontFamily: mono, fontSize: 25, lineHeight: 1.6}}>
        <div style={{color: C.dim, marginBottom: 8}}>edited world, network log</div>
        {log.map((l) =>
          l.t <= now ? (
            l.status === '' ? (
              <div key={l.t} style={{color: '#E9A79F', margin: '4px 0'}}>── follow-up: {l.text}</div>
            ) : (
              <div key={l.t} style={{display: 'flex', gap: 26, whiteSpace: 'nowrap'}}>
                <span style={{color: l.status === '404' ? '#F0857A' : '#9FC1D6', fontWeight: 600}}>{l.status}</span>
                <span>{l.text}</span>
                {l.note ? <span style={{color: C.dim}}>{l.note}</span> : null}
              </div>
            )
          ) : null,
        )}
      </div>
      <Hand at={380} size={54} style={{position: 'absolute', left: 1130, top: 104}}>no certificate checks this time</Hand>
    </Scene>
  );
};
