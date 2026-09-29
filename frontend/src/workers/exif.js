/**
 * Minimal, zero-dependency EXIF reader for Stage 2.1.
 * Extracts DateTimeOriginal (0x9003 / 0x0132) and GPS coordinates (0x8825)
 * from the first 128 KB of a JPEG file BEFORE canvas downsampling strips APP1.
 *
 * Honours both little-endian (0x4949, "II") and big-endian (0x4D4D, "MM") TIFF headers.
 * Never throws: any malformed or non-JPEG input returns {}.
 */

export async function parseExif(file) {
  try {
    if (!file || typeof file.slice !== 'function') return {};
    const head = await file.slice(0, 131072).arrayBuffer();
    return parseExifFromBuffer(head);
  } catch (_) {
    return {};
  }
}

export function parseExifFromBuffer(buffer) {
  try {
    if (!buffer || buffer.byteLength < 12) return {};
    const view = new DataView(buffer);

    // Check JPEG SOI marker (0xFFD8)
    if (view.getUint16(0, false) !== 0xFFD8) return {};

    let offset = 2;
    while (offset + 4 <= view.byteLength) {
      const marker = view.getUint16(offset, false);
      if ((marker & 0xFF00) !== 0xFF00) break;

      const size = view.getUint16(offset + 2, false);
      if (size < 2) break;

      // APP1 marker (0xFFE1) with "Exif\0\0" header
      if (marker === 0xFFE1 && offset + 10 <= view.byteLength) {
        const exifHeader = view.getUint32(offset + 4, false);
        const exifZero = view.getUint16(offset + 8, false);
        if (exifHeader === 0x45786966 && exifZero === 0x0000) {
          return parseTiff(view, offset + 10);
        }
      }

      offset += 2 + size;
    }
    return {};
  } catch (_) {
    return {};
  }
}

function parseTiff(view, tiffStart) {
  if (tiffStart + 8 > view.byteLength) return {};

  const byteOrder = view.getUint16(tiffStart, false);
  let littleEndian;
  if (byteOrder === 0x4949) {
    littleEndian = true;
  } else if (byteOrder === 0x4D4D) {
    littleEndian = false;
  } else {
    return {};
  }

  const magic = view.getUint16(tiffStart + 2, littleEndian);
  if (magic !== 0x002A) return {};

  const ifd0RelOffset = view.getUint32(tiffStart + 4, littleEndian);
  const ifd0Offset = tiffStart + ifd0RelOffset;
  if (ifd0Offset + 2 > view.byteLength) return {};

  const ifd0 = readIfdEntries(view, tiffStart, ifd0Offset, littleEndian);
  let dateStr = ifd0.strings[0x9003] || ifd0.strings[0x0132] || null;

  // Walk Exif SubIFD (0x8769) if present
  if (ifd0.longs[0x8769]) {
    const exifIfdOffset = tiffStart + ifd0.longs[0x8769];
    if (exifIfdOffset + 2 <= view.byteLength) {
      const exifIfd = readIfdEntries(view, tiffStart, exifIfdOffset, littleEndian);
      dateStr = exifIfd.strings[0x9003] || exifIfd.strings[0x9004] || dateStr;
    }
  }

  const out = {};
  if (dateStr) {
    const epoch = parseExifDateToEpoch(dateStr);
    if (epoch !== null) {
      out.timestamp_epoch = epoch;
      out.timestamp_iso = new Date(epoch * 1000).toISOString();
    }
  }

  // Walk GPS IFD (0x8825) if present
  if (ifd0.longs[0x8825]) {
    const gpsIfdOffset = tiffStart + ifd0.longs[0x8825];
    if (gpsIfdOffset + 2 <= view.byteLength) {
      const gps = readGpsIfd(view, tiffStart, gpsIfdOffset, littleEndian);
      if (gps.latitude !== null && gps.longitude !== null) {
        out.latitude = gps.latitude;
        out.longitude = gps.longitude;
      }
    }
  }

  return out;
}

function readIfdEntries(view, tiffStart, ifdOffset, littleEndian) {
  const strings = {};
  const longs = {};

  if (ifdOffset + 2 > view.byteLength) return { strings, longs };
  const entryCount = view.getUint16(ifdOffset, littleEndian);

  for (let i = 0; i < entryCount; i++) {
    const entryOffset = ifdOffset + 2 + i * 12;
    if (entryOffset + 12 > view.byteLength) break;

    const tag = view.getUint16(entryOffset, littleEndian);
    const type = view.getUint16(entryOffset + 2, littleEndian);
    const count = view.getUint32(entryOffset + 4, littleEndian);
    const valueOffsetField = entryOffset + 8;

    // ASCII string (type 2) — e.g. DateTimeOriginal (20 bytes "YYYY:MM:DD HH:MM:SS\0")
    if (type === 2 && count > 0 && count <= 64) {
      const strOffset = count <= 4 ? valueOffsetField : tiffStart + view.getUint32(valueOffsetField, littleEndian);
      if (strOffset >= 0 && strOffset + count <= view.byteLength) {
        let s = '';
        for (let j = 0; j < count - 1; j++) {
          const ch = view.getUint8(strOffset + j);
          if (ch === 0) break;
          s += String.fromCharCode(ch);
        }
        strings[tag] = s.trim();
      }
    }

    // LONG pointer/value (type 4) or SHORT (type 3)
    if (type === 4 && count === 1) {
      longs[tag] = view.getUint32(valueOffsetField, littleEndian);
    } else if (type === 3 && count === 1) {
      longs[tag] = view.getUint16(valueOffsetField, littleEndian);
    }
  }

  return { strings, longs };
}

function readGpsIfd(view, tiffStart, gpsOffset, littleEndian) {
  if (gpsOffset + 2 > view.byteLength) return { latitude: null, longitude: null };
  const entryCount = view.getUint16(gpsOffset, littleEndian);

  let latRef = 'N';
  let lonRef = 'E';
  let latDms = null;
  let lonDms = null;

  for (let i = 0; i < entryCount; i++) {
    const entryOffset = gpsOffset + 2 + i * 12;
    if (entryOffset + 12 > view.byteLength) break;

    const tag = view.getUint16(entryOffset, littleEndian);
    const type = view.getUint16(entryOffset + 2, littleEndian);
    const count = view.getUint32(entryOffset + 4, littleEndian);
    const valueOffsetField = entryOffset + 8;

    // 0x0001 = GPSLatitudeRef, 0x0003 = GPSLongitudeRef (ASCII)
    if ((tag === 0x0001 || tag === 0x0003) && type === 2 && count >= 1) {
      const ch = String.fromCharCode(view.getUint8(valueOffsetField)).toUpperCase();
      if (tag === 0x0001 && (ch === 'N' || ch === 'S')) latRef = ch;
      if (tag === 0x0003 && (ch === 'E' || ch === 'W')) lonRef = ch;
    }

    // 0x0002 = GPSLatitude, 0x0004 = GPSLongitude (3 RATIONALs = 24 bytes)
    if ((tag === 0x0002 || tag === 0x0004) && type === 5 && count === 3) {
      const ratOffset = tiffStart + view.getUint32(valueOffsetField, littleEndian);
      if (ratOffset >= 0 && ratOffset + 24 <= view.byteLength) {
        const dms = [];
        for (let r = 0; r < 3; r++) {
          const num = view.getUint32(ratOffset + r * 8, littleEndian);
          const den = view.getUint32(ratOffset + r * 8 + 4, littleEndian);
          dms.push(den === 0 ? 0 : num / den);
        }
        if (tag === 0x0002) latDms = dms;
        if (tag === 0x0004) lonDms = dms;
      }
    }
  }

  if (!latDms || !lonDms) return { latitude: null, longitude: null };

  let lat = latDms[0] + latDms[1] / 60 + latDms[2] / 3600;
  let lon = lonDms[0] + lonDms[1] / 60 + lonDms[2] / 3600;
  if (latRef === 'S') lat = -lat;
  if (lonRef === 'W') lon = -lon;

  if (!Number.isFinite(lat) || !Number.isFinite(lon) || (lat === 0 && lon === 0)) {
    return { latitude: null, longitude: null };
  }

  return {
    latitude: parseFloat(lat.toFixed(6)),
    longitude: parseFloat(lon.toFixed(6))
  };
}

/**
 * Parses EXIF DateTime format "YYYY:MM:DD HH:MM:SS" into Unix epoch seconds.
 */
export function parseExifDateToEpoch(exifDateStr) {
  if (!exifDateStr || typeof exifDateStr !== 'string') return null;
  const match = exifDateStr.trim().match(/^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/);
  if (!match) return null;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);

  if (year < 1970 || year > 2100 || month < 1 || month > 12 || day < 1 || day > 31) {
    return null;
  }

  const ms = Date.UTC(year, month - 1, day, hour, minute, second);
  if (!Number.isFinite(ms)) return null;
  return Math.floor(ms / 1000);
}
