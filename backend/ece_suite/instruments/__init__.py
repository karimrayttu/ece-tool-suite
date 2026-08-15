"""Instrument abstraction layer (IAL).

A vendor-neutral SCPI core with two interchangeable transports — SimTransport and the real
VisaTransport — behind one interface, so moving from simulator to bench hardware is a
config swap, not a rewrite. Waveform decode (Keysight preamble math) is a pure function so
the same code path serves sim and real.
"""
