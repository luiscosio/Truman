import {loadFont as loadArchivo} from '@remotion/google-fonts/Archivo';
import {loadFont as loadCaveat} from '@remotion/google-fonts/Caveat';
import {loadFont as loadMono} from '@remotion/google-fonts/JetBrainsMono';

export const sans = loadArchivo('normal', {weights: ['400', '500', '700', '800'], subsets: ['latin']}).fontFamily;
export const hand = loadCaveat('normal', {weights: ['600', '700'], subsets: ['latin']}).fontFamily;
export const mono = loadMono('normal', {weights: ['400', '600'], subsets: ['latin']}).fontFamily;

export const C = {
  plate: '#CFD3CD',
  plateDeep: '#BFC4BD',
  ink: '#22262A',
  inkSoft: '#4A5056',
  dim: '#7A817C',
  grease: '#C93A2E',
  cyan: '#3E6A86',
  card: '#E4E7E2',
  glow: '#E9ECE6',
};

export const W = 1920;
export const H = 1080;
export const M = 140;
