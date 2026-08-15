"""Simulated instruments.

Each model subclasses :class:`SimInstrument` (which implements the ``Transport`` interface)
and answers SCPI from an in-memory model. Everything they return is provenance SIMULATED —
the honesty contract makes that impossible to forget downstream.
"""

from .base import SimInstrument
from .dmm import SimDMM
from .eload import SimEload
from .fluke_dmm import SimFlukeDMM
from .funcgen import SimFuncGen
from .psu import SimPSU
from .scope import SimScope
from .spectrum import SimSpectrumAnalyzer

__all__ = ["SimInstrument", "SimScope", "SimDMM", "SimSpectrumAnalyzer", "SimPSU",
           "SimFuncGen", "SimEload", "SimFlukeDMM"]
