// Protocol van de P-Cardio over Bluetooth (Nordic UART Service), zonder DOM en zonder Bluetooth-API.
// Overgezet uit streamlit/kern/pcardio_protocol.py en pcardio.py, zonder de dongle-framing ($T/$R).
// Bron: docs/PCardio - Interface v7.0.pdf. Test: streamlit/tests/test_mobiel.py (vergelijkt met de Python-code).

// §2.1: één GATT-service; schrijven naar RX, notificaties op TX.
export const NUS = "6e400001-b5a3-f393-e0a9-e50e24dcca9e";
export const RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e";
export const TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e";

// Core Interface (§4) en memory map (§5).
const OP_LEES = 1, OP_DATA = 2, OP_STREAM = 4;
const CORE_HEADER = 7; // opcode (1), adres (4), lengte (2), little-endian
export const ABORT = new Uint8Array([3]); // stopt de stream (opcode 3, zie pcardio_protocol.py)
export const PIN_ADRES = 128;
export const PIN = new Uint8Array([0x6c, 0x6f, 0x76, 0x65]);
export const CONFIG_ADRES = 276, CONFIG_LENGTE = 68;
export const STREAM_ADRES = 0x10000000;

function core(opcode, adres, lengte, data = new Uint8Array()) {
  const pakket = new Uint8Array(CORE_HEADER + data.length);
  const v = new DataView(pakket.buffer);
  v.setUint8(0, opcode);
  v.setUint32(1, adres, true);
  v.setUint16(5, lengte, true);
  pakket.set(data, CORE_HEADER);
  return pakket;
}

export const leesPakket = (adres, lengte) => core(OP_LEES, adres, lengte);
export const dataPakket = (adres, data) => core(OP_DATA, adres, data.length, data);
export const streamPakket = (lengte) => core(OP_STREAM, STREAM_ADRES, lengte);

/** Knipt binnenkomende notificaties op in Data-pakketten {adres, data}. Meestal is één notificatie één pakket;
 *  een pakket dat over notificaties verdeeld is, wordt ook goed samengevoegd. Rommel leegt de buffer. */
export class CoreStroom {
  #buffer = new Uint8Array();

  voegToe(bytes) {
    const b = new Uint8Array(this.#buffer.length + bytes.length);
    b.set(this.#buffer);
    b.set(bytes, this.#buffer.length);
    const pakketten = [];
    let i = 0;
    while (b.length - i >= CORE_HEADER) {
      const v = new DataView(b.buffer, i);
      const lengte = v.getUint16(5, true);
      if (b[i] !== OP_DATA || lengte > 1024) {
        i = b.length;
        break;
      }
      if (b.length - i < CORE_HEADER + lengte) break;
      pakketten.push({ adres: v.getUint32(1, true), data: b.slice(i + CORE_HEADER, i + CORE_HEADER + lengte) });
      i += CORE_HEADER + lengte;
    }
    this.#buffer = b.slice(i);
    return pakketten;
  }
}

/** Voegt Data-pakketten op opeenvolgende adressen samen tot één blok (zoals Samenvoeger in Python). */
export class Samenvoeger {
  constructor(start, grootte) {
    Object.assign(this, { start, grootte, delen: [], lengte: 0, verloren: 0 });
  }

  voegToe({ adres, data }) {
    const positie = adres - this.start;
    if (positie !== this.lengte) {
      if (this.lengte) this.verloren++;
      this.delen = [];
      this.lengte = 0;
      if (positie) return null;
    }
    this.delen.push(data);
    this.lengte += data.length;
    if (this.lengte < this.grootte) return null;
    const blok = new Uint8Array(this.lengte);
    let o = 0;
    for (const d of this.delen) {
      blok.set(d, o);
      o += d.length;
    }
    this.delen = [];
    this.lengte = 0;
    return blok.subarray(0, this.grootte);
  }
}

// §7: sensoren en datatypes (zelfde tabellen als kern/pcardio.py).
const RATES = [1000, 800, 500, 400, 250, 200, 100, 50, 25, 10, 5];
const GAINS = [1, 2, 3, 4, 6, 8, 12, 16];
const SENSOREN = {
  0: ["batterij", ["Batterij"]],
  1: ["ecg", ["Ecg1"]],
  2: ["bioz", ["BioZ"]],
  3: ["ecg", ["Ecg1", "Ecg2"]],
  4: ["emg", ["Emg1", "Emg2"]],
  5: ["acc", ["AccX", "AccY", "AccZ"]],
  6: ["gyro", ["GyrX", "GyrY", "GyrZ"]],
  7: ["mag", ["MagX", "MagY", "MagZ"]],
  10: ["button_marker", ["Button"]],
  11: ["tap_marker", ["Tap"]],
  12: ["lead_off", ["LeadOff"]],
};
// eenheid, grootte (bytes), elementen, signed, analoog min/max, digitaal min/max
const DATATYPES = {
  0: ["%", 1, 1, false, 0, 100, 0, 100],
  1: ["mV", 3, 1, true, -2420, 2420, -8388608, 8388607],
  2: ["Ohm", 3, 1, true, -80666.67, 80666.67, -262144, 262143],
  3: ["mV", 6, 2, true, -2420, 2420, -8388608, 8388607],
  4: ["g", 6, 3, true, -16, 16, -32768, 32767],
  5: ["deg/s", 6, 3, true, -2000, 2000, -28571, 28570],
  6: ["rad/s", 6, 3, true, -34.906585, 34.906585, -28571, 28570],
  7: ["Gauss", 6, 3, true, -49.125, 49.125, -32768, 32767],
  8: ["", 1, 1, false, 0, 1, 0, 1],
};
const PAKKET_HEADER = 13; // tijd (4), ticks (4), status (1), payloadgrootte (2), checksum (2)

function sensorConfig(sensorId, gainId, rateId, typeId) {
  if (!(sensorId in SENSOREN) || !(typeId in DATATYPES) || gainId >= GAINS.length || rateId >= RATES.length) {
    throw new Error(`Onbekende sensor of datatype in de configuratie: ${[sensorId, gainId, rateId, typeId]}`);
  }
  const [naam, kanalen] = SENSOREN[sensorId];
  const [eenheid, grootte, elementen, signed, amin, amax, dmin, dmax] = DATATYPES[typeId];
  const n = RATES[rateId] / 5; // 5 pakketten per seconde
  return {
    naam, kanalen, eenheid, elementen, signed, amax, dmax, n,
    fs: RATES[rateId],
    gain: GAINS[gainId],
    breedte: grootte / elementen,
    schaal: (amax - amin) / (dmax - dmin),
    blokgrootte: grootte * n,
  };
}

export function decodeerConfig(data) {
  const aantal = new DataView(data.buffer, data.byteOffset).getUint32(0, true);
  if (aantal > 16) throw new Error(`Sampling-configuratie noemt ${aantal} sensoren; maximaal 16.`);
  return Array.from({ length: aantal }, (_, i) => sensorConfig(...data.subarray(4 + 4 * i, 8 + 4 * i)));
}

export const pakketgrootte = (configs) => PAKKET_HEADER + configs.reduce((som, c) => som + c.blokgrootte, 0);

/** CRC-16-CCITT (0x1021, start 0xFFFF) over de payload, zoals binascii.crc_hqx. */
export function crc16(bytes) {
  let c = 0xffff;
  for (const b of bytes) {
    c ^= b << 8;
    for (let i = 0; i < 8; i++) c = c & 0x8000 ? ((c << 1) ^ 0x1021) & 0xffff : (c << 1) & 0xffff;
  }
  return c;
}

function geheel(b, o, breedte, signed) {
  let w = 0;
  for (let k = breedte - 1; k >= 0; k--) w = w * 256 + b[o + k];
  return signed && w >= 2 ** (8 * breedte - 1) ? w - 2 ** (8 * breedte) : w;
}

/** §6: één datapakket -> {tijd, status, crcOk, sensoren: [[config, waarden (samples × elementen)]]}. */
export function parseDatapakket(pakket, configs) {
  const v = new DataView(pakket.buffer, pakket.byteOffset, pakket.byteLength);
  const grootte = v.getUint16(9, true);
  const payload = pakket.subarray(PAKKET_HEADER, PAKKET_HEADER + grootte);
  const verwacht = pakketgrootte(configs) - PAKKET_HEADER;
  if (grootte !== verwacht || payload.length !== grootte) {
    throw new Error(`Payload is ${grootte} bytes volgens de header (${payload.length} ontvangen), verwacht ${verwacht}.`);
  }
  let o = 0;
  const sensoren = configs.map((c) => {
    const waarden = [];
    for (let s = 0; s < c.n; s++) {
      const rij = [];
      for (let e = 0; e < c.elementen; e++, o += c.breedte) {
        rij.push((c.schaal * (geheel(payload, o, c.breedte, c.signed) - c.dmax) + c.amax) / c.gain);
      }
      waarden.push(rij);
    }
    return [c, waarden];
  });
  return {
    tijd: v.getUint32(0, true) + v.getUint32(4, true) / 32768,
    status: v.getUint8(8), // bit 0 logt, bit 1 streamt (§6.1.3)
    crcOk: crc16(payload) === v.getUint16(11, true),
    sensoren,
  };
}
