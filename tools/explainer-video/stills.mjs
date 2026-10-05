// Render chosen frames as half-size PNGs, for checking layout without a full render.
// Usage: node stills.mjs 240 1064 2950
import {mkdirSync} from 'node:fs';
import path from 'node:path';
import {bundle} from '@remotion/bundler';
import {renderStill, selectComposition} from '@remotion/renderer';

const frames = process.argv.slice(2).map(Number);
mkdirSync('out/stills', {recursive: true});
const serveUrl = await bundle({entryPoint: path.resolve('src/index.ts')});
const composition = await selectComposition({serveUrl, id: 'TrumanExplainer'});
for (const frame of frames) {
  await renderStill({serveUrl, composition, frame, output: `out/stills/f${String(frame).padStart(4, '0')}.png`, scale: 0.5});
  console.log('still', frame);
}
