"""
geo.py -- Minimal GeoJSON choropleth for NYC boroughs (numpy + matplotlib only).

No geopandas/shapely (pandas is broken in this environment).  Parses GeoJSON
with stdlib json, fills borough polygons as matplotlib patches, and shades them
by value with a palette-matched sequential colormap.
"""
from __future__ import annotations
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.collections import PatchCollection
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.cm import ScalarMappable

NYC_LAT = 40.7  # for lon/lat aspect correction


def load_boroughs(path):
    """Return {borough_name: [exterior_ring_arrays]} from a GeoJSON file.

    Interior rings (holes) are ignored -- adequate for an illustrative borough
    map and avoids needing shapely for even-odd fills.
    """
    d = json.load(open(path))
    out = {}
    for f in d["features"]:
        name = f["properties"].get("name") or f["properties"].get("BoroName")
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        rings = [np.asarray(poly[0], float) for poly in polys]  # exterior only
        out[name] = rings
    return out


def _shoelace_area(ring):
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))


def _label_point(rings):
    """Centroid of the largest ring -- where to drop the borough label."""
    big = max(rings, key=_shoelace_area)
    return big[:, 0].mean(), big[:, 1].mean()


def sequential_cmap(hex_to, name="seq"):
    """White -> hex_to linear colormap (palette-matched single-hue)."""
    return LinearSegmentedColormap.from_list(name, ["#ffffff", hex_to])


def choropleth(ax, boroughs, values, cmap, *, vmin=None, vmax=None,
               edge="#ffffff", label_fmt=None, label_color="#1a1a1a"):
    """Fill each borough by its value; add labels.  Returns the ScalarMappable."""
    vmax = vmax if vmax is not None else max(values.values())
    vmin = vmin if vmin is not None else 0.0
    norm = Normalize(vmin=vmin, vmax=vmax)
    for name, rings in boroughs.items():
        val = values.get(name, 0.0)
        color = cmap(norm(val))
        patches = [MplPolygon(r, closed=True) for r in rings]
        ax.add_collection(PatchCollection(patches, facecolor=color,
                                          edgecolor=edge, linewidths=0.8))
        if label_fmt:
            lx, ly = _label_point(rings)
            tcol = "white" if norm(val) > 0.5 else label_color  # readable on dark fills
            ax.text(lx, ly, label_fmt(name, val), ha="center", va="center",
                    fontsize=8.5, color=tcol, fontweight="bold")
    # frame
    allx = np.concatenate([r[:, 0] for rs in boroughs.values() for r in rs])
    ally = np.concatenate([r[:, 1] for rs in boroughs.values() for r in rs])
    ax.set_xlim(allx.min() - 0.01, allx.max() + 0.01)
    ax.set_ylim(ally.min() - 0.01, ally.max() + 0.01)
    ax.set_aspect(1.0 / np.cos(np.radians(NYC_LAT)))
    ax.axis("off")
    sm = ScalarMappable(norm=norm, cmap=cmap); sm.set_array([])
    return sm


if __name__ == "__main__":
    b = load_boroughs("../data/nyc_boroughs.geojson")
    print("loaded boroughs:", {k: len(v) for k, v in b.items()})
