import React from 'react';
import {AbsoluteFill, interpolate, random, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {C, H, W, hand, sans} from './theme';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

export const progress = (frame: number, start: number, length: number) =>
  interpolate(frame, [start, start + length], [0, 1], clamp);

// A photographic plate: glass tone, vignette, moving grain. `negative` flips to a dark plate.
export const Plate: React.FC<{negative?: boolean; children?: React.ReactNode}> = ({negative, children}) => {
  const frame = useCurrentFrame();
  const base = negative ? C.ink : C.plate;
  const edge = negative ? '#15181B' : C.plateDeep;
  return (
    <AbsoluteFill style={{backgroundColor: base, fontFamily: sans, color: negative ? C.glow : C.ink}}>
      <AbsoluteFill style={{background: `radial-gradient(ellipse at 50% 45%, transparent 55%, ${edge} 100%)`}} />
      {children}
      <svg width={W} height={H} style={{position: 'absolute', inset: 0, opacity: negative ? 0.1 : 0.16, mixBlendMode: negative ? 'screen' : 'multiply', pointerEvents: 'none'}}>
        <filter id="grain">
          <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" seed={Math.floor(frame / 2)} />
          <feColorMatrix type="saturate" values="0" />
        </filter>
        <rect width="100%" height="100%" filter="url(#grain)" />
      </svg>
    </AbsoluteFill>
  );
};

// Star field from a seed; stars are dark on a light plate, as on Tombaugh's negatives.
export const Stars: React.FC<{seed: string; count: number; negative?: boolean; opacity?: number}> = ({seed, count, negative, opacity = 1}) => (
  <svg width={W} height={H} style={{position: 'absolute', inset: 0, opacity}}>
    {Array.from({length: count}, (_, i) => {
      const r = 0.7 + Math.pow(random(`${seed}r${i}`), 4) * 4.2;
      return <circle key={i} cx={random(`${seed}x${i}`) * W} cy={random(`${seed}y${i}`) * H} r={r} fill={negative ? C.glow : C.ink} opacity={0.35 + random(`${seed}o${i}`) * 0.6} />;
    })}
  </svg>
);

export const Scene: React.FC<{negative?: boolean; children: React.ReactNode}> = ({negative, children}) => (
  <Plate negative={negative}>
    {children}
  </Plate>
);

export const Fade: React.FC<{at: number; children: React.ReactNode; style?: React.CSSProperties; lift?: number}> = ({at, children, style, lift = 10}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = spring({frame: frame - at, fps, config: {damping: 200}, durationInFrames: 20});
  return <div style={{opacity: p, transform: `translateY(${(1 - p) * lift}px)`, ...style}}>{children}</div>;
};

// Grease-pencil text written left to right.
export const Hand: React.FC<{at: number; children: React.ReactNode; size?: number; color?: string; style?: React.CSSProperties; length?: number}> = ({at, children, size = 56, color = C.grease, style, length = 18}) => {
  const frame = useCurrentFrame();
  const p = progress(frame, at, length);
  return (
    <div style={{fontFamily: hand, fontWeight: 700, fontSize: size, color, lineHeight: 1, clipPath: `inset(-20% ${(1 - p) * 110 - 10}% -20% -5%)`, paddingRight: 12, whiteSpace: 'nowrap', ...style}}>
      {children}
    </div>
  );
};

const loop = (w: number, h: number, seed: string) => {
  const points: string[] = [];
  const n = 72;
  for (let i = 0; i <= n; i++) {
    const t = (i / n) * 2 * Math.PI * 1.1 - 0.7;
    const wobble = 1 + (random(`${seed}${i}`) - 0.5) * 0.035 + 0.025 * Math.sin(t * 3);
    points.push(`${(w / 2 + Math.cos(t) * (w / 2 - 8) * wobble).toFixed(1)},${(h / 2 + Math.sin(t) * (h / 2 - 8) * wobble).toFixed(1)}`);
  }
  return `M${points.join(' L')}`;
};

// A hand-drawn ring around something, drawn over `length` frames.
export const Ring: React.FC<{at: number; x: number; y: number; w: number; h: number; seed?: string; length?: number; color?: string; stroke?: number}> = ({at, x, y, w, h, seed = 'ring', length = 16, color = C.grease, stroke = 6}) => {
  const frame = useCurrentFrame();
  const p = progress(frame, at, length);
  return (
    <svg width={w} height={h} style={{position: 'absolute', left: x, top: y, overflow: 'visible'}}>
      <path d={loop(w, h, seed)} pathLength={1} fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeDasharray={1} strokeDashoffset={1 - p} opacity={0.92} />
    </svg>
  );
};

// A hand-drawn stroke: underline or strike-through.
export const Stroke: React.FC<{at: number; x: number; y: number; w: number; length?: number; color?: string; stroke?: number; tilt?: number}> = ({at, x, y, w, length = 10, color = C.grease, stroke = 6, tilt = -4}) => {
  const frame = useCurrentFrame();
  const p = progress(frame, at, length);
  return (
    <svg width={w + 20} height={60} style={{position: 'absolute', left: x - 10, top: y - 30, overflow: 'visible'}}>
      <path d={`M10,${30 - tilt / 2} Q${w / 2},${30 + tilt} ${w + 10},${30 + tilt / 2}`} pathLength={1} fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeDasharray={1} strokeDashoffset={1 - p} opacity={0.92} />
    </svg>
  );
};

// Typed label, as on a plate sleeve.
export const Label: React.FC<{children: React.ReactNode; color?: string; style?: React.CSSProperties}> = ({children, color = C.inkSoft, style}) => (
  <div style={{fontFamily: sans, fontWeight: 500, fontSize: 28, color, letterSpacing: 0.2, ...style}}>{children}</div>
);

export const Typed: React.FC<{at: number; text: string; cps?: number; style?: React.CSSProperties}> = ({at, text, cps = 40, style}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const shown = Math.max(0, Math.floor(((frame - at) / fps) * cps));
  const done = shown >= text.length;
  const caret = !done && frame >= at && Math.floor(frame / 8) % 2 === 0;
  return (
    <span style={style}>
      {text.slice(0, shown)}
      <span style={{opacity: caret ? 1 : 0}}>▌</span>
    </span>
  );
};
