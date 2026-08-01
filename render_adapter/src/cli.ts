/**
 * CLI / end-to-end demo: node cli.ts [depthMapPath] [stylePrompt] [outputDir]
 *
 * Runs one room's depth map through MockStylingProvider and then through
 * the checkGeometryDrift stub, printing the results as JSON. Demonstrates
 * the full plumbing works without needing a real vendor, API key, or even
 * a depth map from scene/'s export_views.ts — if no depthMapPath is given,
 * a small synthetic gradient depth map is generated on the fly.
 */
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import { checkGeometryDrift } from './drift_check.js';
import { encodeGrayscalePNG } from './png.js';
import { MockStylingProvider } from './providers/mock_provider.js';

function makeSyntheticDepthMap(outputPath: string, width = 200, height = 150): void {
  const pixels = new Uint8Array(width * height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      // A simple diagonal gradient — just needs to be non-uniform, it's
      // not meant to represent a real room.
      pixels[y * width + x] = Math.round(((x / width + y / height) / 2) * 255);
    }
  }
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, encodeGrayscalePNG(width, height, pixels));
}

async function main(): Promise<void> {
  const [depthMapArg, stylePromptArg, outputDirArg] = process.argv.slice(2);

  let depthMapPath = depthMapArg;
  if (!depthMapPath) {
    depthMapPath = path.join(os.tmpdir(), 'render-adapter-cli-demo', 'synthetic_room_depth.png');
    makeSyntheticDepthMap(depthMapPath);
    console.log(`no depthMapPath given — generated a synthetic one at ${depthMapPath}`);
  }

  const stylePrompt = stylePromptArg ?? 'contemporary minimalist, warm wood tones, soft daylight';
  const outputDir = outputDirArg ?? path.dirname(depthMapPath);

  const provider = new MockStylingProvider({ outputDir });
  const styleResult = await provider.styleImage({
    depthMapPath,
    stylePrompt,
    conditioningStrength: 0.8,
  });
  console.log('styleImage result:', JSON.stringify(styleResult, null, 2));

  const driftResult = await checkGeometryDrift(depthMapPath, styleResult.imagePath);
  console.log('checkGeometryDrift result:', JSON.stringify(driftResult, null, 2));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
