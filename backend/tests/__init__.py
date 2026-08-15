"""Test package.

Marks this directory as a regular package so intra-suite imports (``from tests.test_kicad
import FIXTURE``) resolve to THIS directory and not to a same-named top-level ``tests`` package
that a dependency's wheel may install into site-packages (PyOpenMagnetics 1.6.1 ships one).
"""
