import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { test } from 'node:test';

import { checkGeometryDrift } from '../src/drift_check.js';
import { decodeGrayscalePNG, encodeGrayscalePNG } from '../src/png.js';
import { MockStylingProvider } from '../src/providers/mock_provider.js';

function makeFixtureDepthMap(dir: string, width = 64, height = 48): string {
  const pixels = new Uint8Array(width * height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      pixels[y * width + x] = Math.round(((x / width + y / height) / 2) * 255);
    }
  }
  const filePath = path.join(dir, 'fixture_depth.png');
  fs.writeFileSync(filePath, encodeGrayscalePNG(width, height, pixels));
  return filePath;
}

test('MockStylingProvider + checkGeometryDrift run end to end without a real vendor', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'render-adapter-test-'));
  try {
    const depthMapPath = makeFixtureDepthMap(dir);

    const provider = new MockStylingProvider({ outputDir: dir });
    const styleResult = await provider.styleImage({
      depthMapPath,
      stylePrompt: 'contemporary minimalist, warm wood tones',
      conditioningStrength: 0.6,
    });

    assert.equal(styleResult.providerName, 'mock');
    assert.equal(styleResult.costEstimate, 0);
    assert.ok(fs.existsSync(styleResult.imagePath), 'styled output file should exist');

    const driftResult = await checkGeometryDrift(depthMapPath, styleResult.imagePath);
    assert.equal(driftResult.method, 'stub');
    assert.equal(driftResult.passed, true);
    assert.equal(driftResult.driftScore, null);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('MockStylingProvider output matches the input depth map dimensions', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'render-adapter-test-'));
  try {
    const depthMapPath = makeFixtureDepthMap(dir, 80, 40);
    const provider = new MockStylingProvider({ outputDir: dir });
    const styleResult = await provider.styleImage({
      depthMapPath,
      stylePrompt: 'test',
      conditioningStrength: 0.5,
    });

    const { width: srcWidth, height: srcHeight } = decodeGrayscalePNG(fs.readFileSync(depthMapPath));

    // The mock output is RGB (color type 2); just check the IHDR dimensions
    // via the raw bytes since decodeGrayscalePNG only supports color type 0.
    const outBuf = fs.readFileSync(styleResult.imagePath);
    const outWidth = outBuf.readUInt32BE(16);
    const outHeight = outBuf.readUInt32BE(20);

    assert.equal(outWidth, srcWidth);
    assert.equal(outHeight, srcHeight);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('checkGeometryDrift stub throws if a given path does not exist', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'render-adapter-test-'));
  try {
    const depthMapPath = makeFixtureDepthMap(dir);
    await assert.rejects(() => checkGeometryDrift(depthMapPath, path.join(dir, 'missing.png')));
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('MockStylingProvider does not perform any network calls or require vendor deps', async () => {
  // Structural guard, not a network-level assertion: importing the mock
  // provider must not have pulled in an HTTP client / vendor SDK.
  const pkg = JSON.parse(fs.readFileSync(new URL('../package.json', import.meta.url), 'utf-8'));
  assert.deepEqual(pkg.dependencies, {}, 'render_adapter must have zero runtime dependencies until a vendor is selected');
});
