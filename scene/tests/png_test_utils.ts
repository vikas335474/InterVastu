/** Minimal PNG reading helpers for tests only — decodes what our own encoder produces. */
import { inflateSync } from 'node:zlib';

export function readPngDimensions(buf: Buffer): { width: number; height: number; colorType: number } {
  const ihdrOffset = 8 + 8; // signature + IHDR length/type
  return {
    width: buf.readUInt32BE(ihdrOffset),
    height: buf.readUInt32BE(ihdrOffset + 4),
    colorType: buf.readUInt8(ihdrOffset + 9),
  };
}

/** Decodes an 8-bit grayscale, filter-type-0, non-interlaced PNG (i.e. one written by png_encoder.ts). */
export function decodeGrayscalePNG(buf: Buffer): { width: number; height: number; pixels: Uint8Array } {
  const { width, height, colorType } = readPngDimensions(buf);
  if (colorType !== 0) throw new Error(`expected grayscale (colorType 0), got ${colorType}`);

  const idatChunks: Buffer[] = [];
  let offset = 8;
  while (offset < buf.length) {
    const len = buf.readUInt32BE(offset);
    const type = buf.toString('ascii', offset + 4, offset + 8);
    if (type === 'IDAT') idatChunks.push(buf.subarray(offset + 8, offset + 8 + len));
    offset += 12 + len;
  }
  const raw = inflateSync(Buffer.concat(idatChunks));

  const pixels = new Uint8Array(width * height);
  for (let y = 0; y < height; y++) {
    const rowStart = y * (width + 1);
    const filterType = raw[rowStart];
    if (filterType !== 0) throw new Error(`unsupported PNG filter type ${filterType}`);
    pixels.set(raw.subarray(rowStart + 1, rowStart + 1 + width), y * width);
  }
  return { width, height, pixels };
}
