/**
 * Minimal dependency-free PNG codec.
 *
 * Decoding only supports what `scene/`'s own encoder produces: 8-bit
 * grayscale (color type 0), non-interlaced, filter type 0 on every
 * scanline — that's the only kind of PNG this module ever needs to read
 * (the depth maps exported by the previous session's `scene/export_views.ts`
 * pipeline). It is NOT a general-purpose PNG decoder.
 *
 * Encoding only supports 8-bit RGB (color type 2), used for the mock
 * provider's "styled" output image.
 */
import { deflateSync, inflateSync } from 'node:zlib';

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(buf: Buffer): number {
  let crc = 0xffffffff;
  for (let i = 0; i < buf.length; i++) {
    crc = CRC_TABLE[(crc ^ buf[i]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type: string, data: Buffer): Buffer {
  const typeBuf = Buffer.from(type, 'ascii');
  const lenBuf = Buffer.alloc(4);
  lenBuf.writeUInt32BE(data.length, 0);
  const crcBuf = Buffer.alloc(4);
  crcBuf.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0);
  return Buffer.concat([lenBuf, typeBuf, data, crcBuf]);
}

const PNG_SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

function encodePNG(width: number, height: number, colorType: 0 | 2, bytesPerPixel: number, pixels: Uint8Array): Buffer {
  const expected = width * height * bytesPerPixel;
  if (pixels.length !== expected) {
    throw new Error(`expected ${expected} pixel bytes, got ${pixels.length}`);
  }

  const ihdrData = Buffer.alloc(13);
  ihdrData.writeUInt32BE(width, 0);
  ihdrData.writeUInt32BE(height, 4);
  ihdrData[8] = 8; // bit depth
  ihdrData[9] = colorType;
  ihdrData[10] = 0; // compression
  ihdrData[11] = 0; // filter
  ihdrData[12] = 0; // interlace

  const stride = width * bytesPerPixel;
  const raw = Buffer.alloc(height * (stride + 1));
  for (let y = 0; y < height; y++) {
    const rowStart = y * (stride + 1);
    raw[rowStart] = 0; // filter type: None
    raw.set(pixels.subarray(y * stride, (y + 1) * stride), rowStart + 1);
  }
  const idatData = deflateSync(raw);

  return Buffer.concat([
    PNG_SIGNATURE,
    chunk('IHDR', ihdrData),
    chunk('IDAT', idatData),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

export function encodeRGBPNG(width: number, height: number, rgb: Uint8Array): Buffer {
  return encodePNG(width, height, 2, 3, rgb);
}

export function encodeGrayscalePNG(width: number, height: number, gray: Uint8Array): Buffer {
  return encodePNG(width, height, 0, 1, gray);
}

export interface DecodedGrayscalePNG {
  width: number;
  height: number;
  pixels: Uint8Array;
}

export function decodeGrayscalePNG(buf: Buffer): DecodedGrayscalePNG {
  if (!buf.subarray(0, 8).equals(PNG_SIGNATURE)) {
    throw new Error('not a PNG file (bad signature)');
  }

  let width = 0;
  let height = 0;
  let colorType = -1;
  const idatChunks: Buffer[] = [];

  let offset = 8;
  while (offset < buf.length) {
    const len = buf.readUInt32BE(offset);
    const type = buf.toString('ascii', offset + 4, offset + 8);
    const data = buf.subarray(offset + 8, offset + 8 + len);
    if (type === 'IHDR') {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      const bitDepth = data.readUInt8(8);
      colorType = data.readUInt8(9);
      const interlace = data.readUInt8(12);
      if (bitDepth !== 8) throw new Error(`unsupported PNG bit depth ${bitDepth} (only 8-bit is supported)`);
      if (interlace !== 0) throw new Error('interlaced PNGs are not supported');
    } else if (type === 'IDAT') {
      idatChunks.push(data);
    }
    offset += 12 + len;
  }

  if (colorType !== 0) {
    throw new Error(`expected an 8-bit grayscale PNG (color type 0), got color type ${colorType}`);
  }

  const raw = inflateSync(Buffer.concat(idatChunks));
  const pixels = new Uint8Array(width * height);
  for (let y = 0; y < height; y++) {
    const rowStart = y * (width + 1);
    const filterType = raw[rowStart];
    if (filterType !== 0) {
      throw new Error(`unsupported PNG filter type ${filterType} (only filter-type-0 scanlines are supported)`);
    }
    pixels.set(raw.subarray(rowStart + 1, rowStart + 1 + width), y * width);
  }
  return { width, height, pixels };
}
