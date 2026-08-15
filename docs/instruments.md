# Instrument support

## What "supported" means here

The runtime has no simulator in it. Every instrument tab starts disconnected and talks to a
real box over VISA. The `Sim*` classes under `backend/ece_suite/instruments/sim/` exist so the
test suite can exercise the drivers without hardware; `main.py` never instantiates one.

Support for a given model is therefore two separate claims, and the code keeps them apart:

- **Recognised.** The `*IDN?` vendor field maps to a known vendor, and a SCPI dialect is
  selected. Nineteen vendors are in `instruments/vendors.py`.
- **Verified on hardware.** Someone connected that model, ran the verify gate, and the
  readings matched the front panel.

A recognised-but-unverified model will usually work, because most bench instruments made in
the last twenty years implement enough of SCPI-1999 to be interchangeable for the operations
this app performs. When it does not work, the failure is normally one command, not the whole
driver, which is why vendor differences live in a lookup table rather than in subclasses.

## Vendors and dialects

`canonical_vendor()` matches the `*IDN?` vendor field against marker substrings for Keysight
(including Agilent and HP), Tektronix, Teledyne LeCroy, Keithley, Rigol, Siglent,
Rohde & Schwarz (including Hameg), Fluke, B&K Precision, National Instruments, GW Instek,
Yokogawa, OWON, Aim-TTi, Chroma, Kikusui, ITECH, Pico Technology and Hantek.

Two scope drivers exist. The default speaks the InfiniiVision-compatible command set
(`:CHANx:SCAL`, `:TIM:SCAL`, `:TRIG:EDGE`, `:MEAS:*`, `:WAV:PRE?` plus an IEEE-488.2
definite-length block) and covers Keysight, Rigol, Siglent, Rohde & Schwarz and GW Instek.
Tektronix uses different waveform and measurement commands, so it has its own.

An unrecognised vendor still connects. It gets the default dialect and a conservative
capability profile.

## Capability profiles

`instruments/capabilities.py` describes what a model can actually do, and the UI reads it to
decide which controls to render. This is deliberately the pessimistic direction: a control
that is missing is an annoyance, while a control that sends a command the instrument does not
implement leaves an entry in the error queue and a reading you cannot trust.

If you add a profile, write it from the programming manual and mark it untested. Someone with
the instrument can confirm it later.

## Transports

`VisaTransport` opens the system VISA layer first (Keysight IO Libraries or NI-VISA, whichever
is registered) and falls back to `pyvisa-py` if there is none. That order matters: USBTMC
enumeration on Windows comes from the vendor VISA, while `pyvisa-py` handles LAN on its own.

| Interface | Needs a vendor VISA | Notes |
|---|---|---|
| LAN (VXI-11, HiSLIP, raw socket) | No | `pyvisa-py` is enough |
| USB (USBTMC) | Yes on Windows | Install Keysight IO Libraries or NI-VISA |
| Serial | No | `pyserial`, from the `hw` extra |
| GPIB | Yes | Needs a vendor GPIB driver and adapter |

Discovery over TCPIP uses `psutil` to enumerate local subnets and `zeroconf` for LXI
announcements. Both come from the `hw` extra; without it, typing the resource string still
works.

## The verify gate

Connecting gets you `UNVERIFIED_HW`, not a measurement. Verify does two things:

1. Queries `*IDN?` and parses vendor, model, serial and firmware.
2. Drains `:SYST:ERR?` until the queue reports empty.

Both have to pass. A populated error queue after a configuration write means the instrument
rejected something, and a reading taken in that state is not trustworthy even if a number came
back. Only after both does the tag become `VERIFIED_HW`, and that tag rides with every reading
into the UI, the WebSocket streams, the audit log and any tool result handed to the assistant.

Trust is one-way. `provenance.py` lets a tag be lowered but not raised, so a disconnect or a
failed read-back cannot be papered over.

## Adding a model

1. Add the vendor's `*IDN?` markers to `_VENDORS` in `instruments/vendors.py` if the vendor is
   new.
2. Add or adjust the capability profile in `instruments/capabilities.py`.
3. Override only the commands that differ. If you are writing a whole new driver, check first
   whether the existing one plus three overrides would do.
4. Add a sim model under `instruments/sim/` so the behaviour is testable without the box.
5. Extend `backend/tests/test_vendors_multivendor.py`.
