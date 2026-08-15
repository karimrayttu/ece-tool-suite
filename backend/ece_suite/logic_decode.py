"""Logic-analyzer protocol decoders (SPI, I2C, UART) and matching signal generators.

Pure functions over per-sample digital channels (lists of 0/1 at a fixed ``sample_rate``), so
they work on data captured from *any* source — a Saleae, a sigrok/FX2LA device, an MSO scope's
digital pod, or an imported CSV/VCD. The generators produce known waveforms for the demo/tests
so decoding is verifiable without hardware.
"""

from __future__ import annotations

from collections.abc import Sequence


def _edges(sig: Sequence[int]) -> list[tuple[int, int, int]]:
    """Yield (index, prev, cur) at each transition."""
    out = []
    for i in range(1, len(sig)):
        if sig[i] != sig[i - 1]:
            out.append((i, sig[i - 1], sig[i]))
    return out


def decode_uart(rx: Sequence[int], sample_rate: float, baud: float,
                databits: int = 8, parity: str = "none", stopbits: int = 1) -> list[dict]:
    spb = sample_rate / baud
    n = len(rx)
    out: list[dict] = []
    i = 1
    while i < n:
        if rx[i - 1] == 1 and rx[i] == 0:            # falling edge = potential start bit
            start = i

            # `start` is read on every call, but every call happens inside this iteration.
            def bit(k: int) -> int:
                idx = int(round(start + (k + 0.5) * spb))  # noqa: B023
                return rx[idx] if 0 <= idx < n else 1

            if bit(0) != 0:                          # not a real start bit
                i += 1
                continue
            val = 0
            for b in range(databits):
                val |= (bit(1 + b) & 1) << b          # LSB first
            k = 1 + databits
            perr = False
            if parity in ("even", "odd"):
                pbit = bit(k)
                k += 1
                ones = bin(val).count("1") + pbit
                perr = (ones % 2 != 0) if parity == "even" else (ones % 2 != 1)
            ferr = bit(k) != 1                        # stop bit must be high
            out.append({
                "value": val, "hex": f"{val:02X}",
                "char": chr(val) if 32 <= val < 127 else "",
                "time_s": start / sample_rate,
                "parity_error": perr, "framing_error": ferr,
            })
            # advance to the middle of the (high) stop bit so the next falling edge = next
            # start bit is not overshot by rounding, then let edge detection find it.
            frame = 1 + databits + (1 if parity != "none" else 0) + stopbits
            i = max(i + 1, int(round(start + (frame - 0.5) * spb)))
        else:
            i += 1
    return out


def decode_spi(clk: Sequence[int], mosi: Sequence[int] | None, miso: Sequence[int] | None,
               cs: Sequence[int] | None, sample_rate: float, cpol: int = 0, cpha: int = 0,
               bitorder: str = "msb", word_size: int = 8, cs_active_low: bool = True) -> list[dict]:
    n = len(clk)
    results: list[dict] = []
    cur_mosi = cur_miso = nbits = byte_start = 0

    def cs_active(idx: int) -> bool:
        if cs is None:
            return True
        return (cs[idx] == 0) if cs_active_low else (cs[idx] == 1)

    for idx in range(1, n):
        if not cs_active(idx):
            cur_mosi = cur_miso = nbits = 0
            continue
        if clk[idx] == clk[idx - 1]:
            continue
        rising = clk[idx - 1] == 0 and clk[idx] == 1
        leading = rising if cpol == 0 else (not rising)   # idle -> active transition
        is_sample = leading if cpha == 0 else (not leading)
        if not is_sample:
            continue
        if nbits == 0:
            byte_start = idx
        mbit = (mosi[idx] & 1) if mosi is not None else 0
        sbit = (miso[idx] & 1) if miso is not None else 0
        if bitorder == "msb":
            cur_mosi = (cur_mosi << 1) | mbit
            cur_miso = (cur_miso << 1) | sbit
        else:
            cur_mosi |= mbit << nbits
            cur_miso |= sbit << nbits
        nbits += 1
        if nbits >= word_size:
            results.append({
                "mosi": cur_mosi, "miso": cur_miso,
                "mosi_hex": f"{cur_mosi:02X}", "miso_hex": f"{cur_miso:02X}",
                "time_s": byte_start / sample_rate,
            })
            cur_mosi = cur_miso = nbits = 0
    return results


def decode_i2c(scl: Sequence[int], sda: Sequence[int], sample_rate: float) -> list[dict]:
    n = len(scl)
    out: list[dict] = []
    bits = val = 0
    state = "idle"        # idle | addr | data
    is_addr = True
    for i in range(1, n):
        s, ps = scl[i], scl[i - 1]
        d, pd = sda[i], sda[i - 1]
        # START / STOP: SDA transitions while SCL is high
        if s == 1 and ps == 1:
            if pd == 1 and d == 0:
                out.append({"type": "start", "time_s": i / sample_rate})
                bits = val = 0
                is_addr = True
                state = "addr"
                continue
            if pd == 0 and d == 1:
                out.append({"type": "stop", "time_s": i / sample_rate})
                state = "idle"
                continue
        # data/ack sampled on SCL rising edge
        if ps == 0 and s == 1 and state in ("addr", "data"):
            if bits < 8:
                val = (val << 1) | d
                bits += 1
            else:                                   # 9th clock = ACK/NACK
                ack = d == 0
                if is_addr:
                    out.append({"type": "address", "value": val >> 1, "hex": f"{val >> 1:02X}",
                                "rw": "read" if val & 1 else "write", "ack": ack,
                                "time_s": i / sample_rate})
                    is_addr = False
                else:
                    out.append({"type": "data", "value": val, "hex": f"{val:02X}",
                                "char": chr(val) if 32 <= val < 127 else "", "ack": ack,
                                "time_s": i / sample_rate})
                bits = val = 0
                state = "data"
    return out


DECODERS = {"spi": decode_spi, "i2c": decode_i2c, "uart": decode_uart}


# =========================================================================
# Signal generators (for the demo + tests)
# =========================================================================
def _bits_to_samples(bits: Sequence[int], spb: int) -> list[int]:
    out: list[int] = []
    for b in bits:
        out.extend([b] * spb)
    return out


def gen_uart(data: Sequence[int], baud: float = 9600, sample_rate: float = 1_000_000) -> dict:
    spb = int(round(sample_rate / baud))
    bits = [1] * spb * 2                            # idle
    for byte in data:
        frame = [0]                                 # start
        frame += [(byte >> k) & 1 for k in range(8)]  # 8 data LSB-first
        frame += [1]                                # stop
        bits += _bits_to_samples(frame, spb)
    bits += [1] * spb * 2
    return {"sample_rate": sample_rate, "channels": {"RX": bits},
            "protocol": "uart", "options": {"baud": baud}}


def gen_spi(data: Sequence[int], spb: int = 8, sample_rate: float = 1_000_000,
            cpol: int = 0, cpha: int = 0) -> dict:
    clk: list[int] = []; mosi: list[int] = []; cs: list[int] = []
    idle = cpol
    lead = 20
    clk += [idle] * lead; mosi += [0] * lead; cs += [1] * lead     # CS idle high
    for byte in data:
        for k in range(8):
            bit = (byte >> (7 - k)) & 1              # MSB first
            # one clock period = idle half then active half; sample on leading edge for cpha0
            first = idle if cpha == 0 else (1 - idle)
            # drive data before the sampling edge
            clk += [first] * (spb // 2) + [1 - first] * (spb // 2)
            mosi += [bit] * spb
            cs += [0] * spb
    clk += [idle] * lead; mosi += [0] * lead; cs += [1] * lead
    return {"sample_rate": sample_rate, "channels": {"CLK": clk, "MOSI": mosi, "CS": cs},
            "protocol": "spi", "options": {"cpol": cpol, "cpha": cpha}}


def gen_i2c(addr: int, data: Sequence[int], read: bool = False, spb: int = 10,
            sample_rate: float = 1_000_000) -> dict:
    scl: list[int] = []; sda: list[int] = []

    def hold(sc: int, sd: int, ln: int) -> None:
        scl.extend([sc] * ln); sda.extend([sd] * ln)

    h = spb // 2
    hold(1, 1, spb)                                  # idle
    hold(1, 0, h)                                    # START: SDA falls while SCL high

    def byte_out(b: int, ackbit: int) -> None:
        for k in range(8):
            bit = (b >> (7 - k)) & 1
            hold(0, bit, h)                          # SCL low, set SDA
            hold(1, bit, h)                          # SCL high, sampled here
        hold(0, ackbit, h)                           # ACK slot
        hold(1, ackbit, h)

    byte_out((addr << 1) | (1 if read else 0), 0)    # address + R/W, ACK
    for b in data:
        byte_out(b, 0)
    hold(0, 0, h)
    hold(1, 0, h)
    hold(1, 1, h)                                    # STOP: SDA rises while SCL high
    hold(1, 1, spb)
    return {"sample_rate": sample_rate, "channels": {"SCL": scl, "SDA": sda},
            "protocol": "i2c", "options": {}}


def sample_capture(protocol: str) -> dict:
    """A ready-made example capture for a protocol (used by the UI 'Load sample')."""
    p = protocol.lower()
    if p == "spi":
        cap = gen_spi([0x9F, 0xEF, 0x40, 0x18])      # e.g. a NOR-flash JEDEC-ID read (0x9F)
        cap["mapping"] = {"clk": "CLK", "mosi": "MOSI", "cs": "CS"}
        return cap
    if p == "i2c":
        cap = gen_i2c(0x50, [0x00, 0x48, 0x69])       # write to EEPROM @0x50: "Hi"
        cap["mapping"] = {"scl": "SCL", "sda": "SDA"}
        return cap
    cap = gen_uart([ord(c) for c in "OK\r\n"])
    cap["mapping"] = {"rx": "RX"}
    return cap
