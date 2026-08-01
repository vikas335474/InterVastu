/**
 * CLI: node export_views.ts <scene_input.json> <output_dir>
 *
 * Runs the whole pipeline: reads a combined room-polygons + solver-output
 * JSON (see types.ts SceneInput), assembles the three.js scene, and
 * headlessly renders one fixed 3/4-angle eye-level view per room to a
 * color PNG and a matching grayscale depth-map PNG.
 *
 * Rendering happens inside a real (headless) browser via Playwright rather
 * than a server-side WebGL library, so the exact same renderer/scene code
 * can be reused for an in-browser interactive viewer later.
 */
import * as esbuild from 'esbuild';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

import { polygonBounds, polygonCentroid } from './coords.js';
import { encodeGrayscalePNG } from './png_encoder.js';
import type { RoomInput, SceneInput, ViewConfig, ViewRenderResult } from './types.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export const IMAGE_WIDTH = 480;
export const IMAGE_HEIGHT = 360;
const EYE_HEIGHT_FT = 5.5;
const CORNER_INSET_FRACTION = 0.15;
const FOV_DEG = 60;

/** Deterministic "one 3/4-angle view from a reasonable eye-level position" per room. */
export function defaultRoomView(room: RoomInput, wallHeightFt: number): ViewConfig {
  const [minX, minY, maxX, maxY] = polygonBounds(room.polygon);
  const centroid = polygonCentroid(room.polygon);
  const diag = Math.hypot(maxX - minX, maxY - minY);

  const cameraPlanX = minX + CORNER_INSET_FRACTION * (maxX - minX);
  const cameraPlanY = minY + CORNER_INSET_FRACTION * (maxY - minY);
  const targetHeight = wallHeightFt * 0.45;

  return {
    roomName: room.name,
    position: [cameraPlanX, EYE_HEIGHT_FT, -cameraPlanY],
    target: [centroid[0], targetHeight, -centroid[1]],
    fovDeg: FOV_DEG,
    near: 0.3,
    far: diag + wallHeightFt + 5,
    width: IMAGE_WIDTH,
    height: IMAGE_HEIGHT,
  };
}

async function bundleBrowserEntry(): Promise<string> {
  const result = await esbuild.build({
    entryPoints: [path.join(__dirname, 'browser', 'render_entry.ts')],
    bundle: true,
    write: false,
    format: 'iife',
    platform: 'browser',
    target: 'es2022',
  });
  return result.outputFiles[0].text;
}

function findLocalChromiumExecutable(): string | undefined {
  const browsersPath = process.env.PLAYWRIGHT_BROWSERS_PATH;
  if (!browsersPath || !fs.existsSync(browsersPath)) return undefined;
  const entries = fs.readdirSync(browsersPath).filter((e) => e.startsWith('chromium-'));
  for (const entry of entries) {
    const candidate = path.join(browsersPath, entry, 'chrome-linux', 'chrome');
    if (fs.existsSync(candidate)) return candidate;
  }
  return undefined;
}

function dataUrlToBuffer(dataUrl: string): Buffer {
  const base64 = dataUrl.slice(dataUrl.indexOf(',') + 1);
  return Buffer.from(base64, 'base64');
}

/** Extracts the R channel from raw RGBA bytes and flips rows so row 0 is the top. */
function rgbaToTopDownGrayscale(rgba: Buffer, width: number, height: number): Uint8Array {
  const gray = new Uint8Array(width * height);
  for (let y = 0; y < height; y++) {
    const srcRow = height - 1 - y; // WebGL readPixels: row 0 is the bottom.
    for (let x = 0; x < width; x++) {
      gray[y * width + x] = rgba[(srcRow * width + x) * 4];
    }
  }
  return gray;
}

export async function exportViews(sceneInput: SceneInput, outputDir: string): Promise<void> {
  fs.mkdirSync(outputDir, { recursive: true });

  const defaultWallHeight = sceneInput.wall_height_ft ?? 10;
  const views = sceneInput.rooms.map((room) =>
    defaultRoomView(room, room.wall_height_ft ?? defaultWallHeight),
  );

  const bundledJs = await bundleBrowserEntry();
  const executablePath = findLocalChromiumExecutable();

  const browser = await chromium.launch({
    executablePath,
    headless: true,
    args: [
      '--no-sandbox',
      '--disable-gpu-sandbox',
      '--enable-unsafe-swiftshader',
      '--use-gl=angle',
      '--use-angle=swiftshader',
      '--ignore-gpu-blocklist',
    ],
  });

  try {
    const page = await browser.newPage();
    page.on('console', (msg) => {
      if (msg.type() === 'error') console.error(`[browser] ${msg.text()}`);
    });
    await page.setContent('<!DOCTYPE html><html><body></body></html>');
    await page.addScriptTag({ content: bundledJs });

    const results: ViewRenderResult[] = await page.evaluate(
      ([input, viewConfigs]) => (window as any).__renderRoomViews(input, viewConfigs),
      [sceneInput, views] as const,
    );

    results.forEach((result, index) => {
      const prefix = String(index).padStart(2, '0');
      const safeName = result.roomName.replace(/[^a-zA-Z0-9_-]/g, '_');

      const colorPath = path.join(outputDir, `${prefix}_${safeName}_color.png`);
      fs.writeFileSync(colorPath, dataUrlToBuffer(result.colorDataUrl));

      const rgba = Buffer.from(result.depthRawRgbaBase64, 'base64');
      const gray = rgbaToTopDownGrayscale(rgba, result.width, result.height);
      const depthPath = path.join(outputDir, `${prefix}_${safeName}_depth.png`);
      fs.writeFileSync(depthPath, encodeGrayscalePNG(result.width, result.height, gray));
    });
  } finally {
    await browser.close();
  }
}

function isMainModule(): boolean {
  return process.argv[1] === fileURLToPath(import.meta.url);
}

if (isMainModule()) {
  const [inputPath, outputDir] = process.argv.slice(2);
  if (!inputPath || !outputDir) {
    console.error('usage: node export_views.ts <scene_input.json> <output_dir>');
    process.exit(1);
  }
  const sceneInput = JSON.parse(fs.readFileSync(inputPath, 'utf-8')) as SceneInput;
  exportViews(sceneInput, outputDir)
    .then(() => console.log(`wrote views to ${outputDir}`))
    .catch((err) => {
      console.error(err);
      process.exit(1);
    });
}
