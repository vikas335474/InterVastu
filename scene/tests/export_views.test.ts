import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import { after, before, test } from 'node:test';

import { exportViews } from '../src/export_views.js';
import type { SceneInput } from '../src/types.js';
import { decodeGrayscalePNG, readPngDimensions } from './png_test_utils.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE_PATH = path.join(__dirname, 'fixtures', 'single_room.json');

let outputDir: string;

before(async () => {
  outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'scene-export-test-'));
  const sceneInput = JSON.parse(fs.readFileSync(FIXTURE_PATH, 'utf-8')) as SceneInput;
  await exportViews(sceneInput, outputDir);
});

after(() => {
  fs.rmSync(outputDir, { recursive: true, force: true });
});

test('writes exactly one color/depth PNG pair for the single-room fixture', () => {
  const files = fs.readdirSync(outputDir).filter((f) => f.endsWith('.png'));
  assert.equal(files.length, 2, `expected 2 PNG files (1 room x color+depth), got: ${files.join(', ')}`);
  assert.ok(files.some((f) => f.includes('_color.png')));
  assert.ok(files.some((f) => f.includes('_depth.png')));
});

test('color and depth images have matching dimensions', () => {
  const colorFile = fs.readdirSync(outputDir).find((f) => f.includes('_color.png'))!;
  const depthFile = fs.readdirSync(outputDir).find((f) => f.includes('_depth.png'))!;

  const colorDims = readPngDimensions(fs.readFileSync(path.join(outputDir, colorFile)));
  const depthDims = readPngDimensions(fs.readFileSync(path.join(outputDir, depthFile)));

  assert.equal(colorDims.width, depthDims.width);
  assert.equal(colorDims.height, depthDims.height);
  assert.ok(colorDims.width > 0 && colorDims.height > 0);
});

test('depth map is a true grayscale PNG with real depth variation, not blank/uniform', () => {
  const depthFile = fs.readdirSync(outputDir).find((f) => f.includes('_depth.png'))!;
  const { pixels } = decodeGrayscalePNG(fs.readFileSync(path.join(outputDir, depthFile)));

  let min = 255;
  let max = 0;
  for (const p of pixels) {
    if (p < min) min = p;
    if (p > max) max = p;
  }

  assert.ok(max - min > 5, `expected meaningful depth variation, got min=${min} max=${max}`);
});
