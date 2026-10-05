"""
palette.py -- Shared colour scheme echoing the NYC bivariate need x access map
(teal / magenta / navy / grey).  Imported by all figure scripts so the deck is
visually consistent.

Role mapping used across the model's charts:
    NAVY    -> published / known (Tier A)         [map's high-need + high-access]
    MAGENTA -> estimated / priority (Tier B)       [map's high-need + low-access]
    TEAL    -> unlisted tail (Tier C) / access      [map's low-need + high-access]
    GREY    -> neutral / grid / low-low
"""

NAVY    = "#2E2D7D"   # known / published
MAGENTA = "#C23B8C"   # estimated / attention
TEAL    = "#23B3A3"   # unlisted tail / access
GREY    = "#CFD3D6"   # neutral
INK     = "#2B2B2B"   # text / dark labels

# darker line variants for good contrast
MAGENTA_DK = "#9C2E70"
TEAL_DK    = "#178F82"

# sequential references from the choropleths, if a chart needs them
RED   = "#C0392B"
GREEN = "#1B7837"
