/**
 * MockStylingProvider — a StylingProvider implementation that does NOT call
 * any AI vendor. It exists purely so the rest of the pipeline (batching,
 * cost tracking, drift-checking) can be built and tested end to end before
 * a real vendor is selected (Phase-0 spike still pending) or any API key
 * exists.
 *
 * It "styles" the depth map by overlaying a flat color wash plus a label
 * (stamped with the tiny embedded bitmap_font) directly onto the depth
 * image. This is deliberately NOT meant to look good — it's a
 * plumbing-only placeholder standing in for a real diffusion/inference
 * call.
 */
import * as fs from 'node:fs';
import * as path from 'node:path';

import { GLYPH_HEIGHT, GLYPH_WIDTH, glyphFor } from '../bitmap_font.js';
import { decodeGrayscalePNG, encodeRGBPNG } from '../png.js';
import type { StyleImageInput, StyleImageResult, StylingProvider } from '../types.js';

const TEXT_SCALE = 3;
const GLYPH_SPACING_PX = 1;
const LABEL_MARGIN_PX = 8;
const LABEL_LINE_GAP_PX = 4;
const TEXT_COLOR: [number, number, number] = [255, 255, 255];

function drawText(
  rgb: Uint8Array,
  width: number,
  height: number,
  text: string,
  originX: number,
  originY: number,
): void {
  for (let i = 0; i < text.length; i++) {
    const glyph = glyphFor(text[i]);
    const charX = originX + i * (GLYPH_WIDTH + GLYPH_SPACING_PX) * TEXT_SCALE;
    for (let gy = 0; gy < GLYPH_HEIGHT; gy++) {
      for (let gx = 0; gx < GLYPH_WIDTH; gx++) {
        if (glyph[gy][gx] !== '1') continue;
        for (let sy = 0; sy < TEXT_SCALE; sy++) {
          for (let sx = 0; sx < TEXT_SCALE; sx++) {
            const px = charX + gx * TEXT_SCALE + sx;
            const py = originY + gy * TEXT_SCALE + sy;
            if (px < 0 || px >= width || py < 0 || py >= height) continue;
            const idx = (py * width + px) * 3;
            rgb[idx] = TEXT_COLOR[0];
            rgb[idx + 1] = TEXT_COLOR[1];
            rgb[idx + 2] = TEXT_COLOR[2];
          }
        }
      }
    }
  }
}

export interface MockStylingProviderOptions {
  /** Directory the "styled" output PNGs are written to. Defaults to the depth map's own directory. */
  outputDir?: string;
  /** Flat wash color [r, g, b] blended over the depth map. */
  washColor?: [number, number, number];
}

export class MockStylingProvider implements StylingProvider {
  readonly providerName = 'mock';
  private readonly outputDir?: string;
  private readonly washColor: [number, number, number];

  constructor(options: MockStylingProviderOptions = {}) {
    this.outputDir = options.outputDir;
    this.washColor = options.washColor ?? [120, 170, 200];
  }

  async styleImage(input: StyleImageInput): Promise<StyleImageResult> {
    const { depthMapPath, stylePrompt, conditioningStrength } = input;
    const { width, height, pixels } = decodeGrayscalePNG(fs.readFileSync(depthMapPath));

    // Arbitrary, mock-only: conditioningStrength nudges how much the flat
    // wash color dominates over the raw depth grayscale, just so the two
    // inputs visibly do *something* different in the output — no relation
    // to how a real vendor would use this parameter.
    const washAlpha = 0.3 + 0.4 * Math.min(1, Math.max(0, conditioningStrength));

    const rgb = new Uint8Array(width * height * 3);
    for (let i = 0; i < width * height; i++) {
      const gray = pixels[i];
      for (let c = 0; c < 3; c++) {
        rgb[i * 3 + c] = Math.round(gray * (1 - washAlpha) + this.washColor[c] * washAlpha);
      }
    }

    const lines = [
      'MOCK STYLED',
      stylePrompt.toUpperCase().slice(0, 40) || '(NO PROMPT)',
      `COND:${conditioningStrength.toFixed(2)}`,
    ];
    let y = LABEL_MARGIN_PX;
    for (const line of lines) {
      drawText(rgb, width, height, line, LABEL_MARGIN_PX, y);
      y += GLYPH_HEIGHT * TEXT_SCALE + LABEL_LINE_GAP_PX;
    }

    const outputDir = this.outputDir ?? path.dirname(depthMapPath);
    fs.mkdirSync(outputDir, { recursive: true });
    const baseName = path.basename(depthMapPath, path.extname(depthMapPath));
    const outputPath = path.join(outputDir, `${baseName}.mock_styled.png`);
    fs.writeFileSync(outputPath, encodeRGBPNG(width, height, rgb));

    return {
      imagePath: outputPath,
      providerName: this.providerName,
      costEstimate: 0,
      rawResponseMeta: {
        mock: true,
        note: 'MockStylingProvider performed no real inference; output is a color-washed, labeled copy of the input depth map.',
        stylePrompt,
        conditioningStrength,
        colorMapPathIgnored: input.colorMapPath ?? null,
      },
    };
  }
}
