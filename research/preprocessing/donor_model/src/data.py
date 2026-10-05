"""
data.py -- Canonical encoding of the inputs for the donor-volume estimation model.

All quantities are in POUNDS PER YEAR (lbs/yr) unless suffixed otherwise.
Two empirical inputs are encoded here:

  1. City Harvest "Food Donors" page  (https://www.cityharvest.org/food-donors/)
     - 12 "most generous donors" with published annual poundage  -> Tier A (anchors)
     - 15 category lists of named donors WITHOUT amounts          -> Tier B (named, latent)
  2. Food Bank For New York City FY2025 audited consolidated financials
     - used only as *external reconciliation anchors* (unit bridge, channel mix)

Design note on units (canonical-unit decision, see writeup S1):
    We model in pounds. Dollar and meal views are derived through fixed bridges
    so that every downstream artifact is comparable across organisations.
"""

# ---------------------------------------------------------------------------
# Constants / unit bridges
# ---------------------------------------------------------------------------

# Feeding America national wholesale value of one pound of donated food.
# Source: Food Bank NYC FY2025 audit, Note 9 ($1.90 for FY2025; $1.97 FY2024).
USD_PER_LB_2025 = 1.90
USD_PER_LB_2024 = 1.97

# Feeding America meal-conversion factor (pounds per meal).
LBS_PER_MEAL = 1.2

# ---------------------------------------------------------------------------
# Control totals (raking targets).  See writeup S4.
# ---------------------------------------------------------------------------
# City Harvest states on the same site that it will divert ~90M lbs from
# landfills "this year".  We treat this as the primary control total and run
# sensitivity against a conservative lower bound consistent with historically
# reported rescue volumes (~75M lbs).
CONTROL_TOTAL_LBS = 90_000_000
CONTROL_TOTAL_SENSITIVITY = (75_000_000, 90_000_000)

# Food Bank NYC FY2025 channel mix (audit Note 9), used as an *independent*
# cross-organisation check on the implied donated/purchased/government split.
# (Food Bank NYC is a different organisation; we use its proportions only as a
# sanity band, never as a hard City Harvest constraint -- see writeup S4.)
FBNYC_FY25 = {
    "donated_lbs":     22_715_407,
    "purchased_lbs":   24_252_727,
    "government_lbs":   56_922_399,
    "total_lbs":      103_890_533,
    "total_value_usd": 126_914_639,
}

# ---------------------------------------------------------------------------
# Tier A -- the 12 published "most generous" donors (name, lbs, category, types)
# ---------------------------------------------------------------------------
# `category` uses the same taxonomy as the roster below so anchors can inform
# the per-category recovery rates.  (The two formerly logo-only anchors have now
# been identified as Jacob's Village Farm (Wholesale) and 4C Foods (Manufacturers);
# they are de-duped out of Tier B via ROSTER_TO_KNOWN_ALIASES below.)
KNOWN_DONORS = [
    # name,                         lbs,        category,        food_types
    ("Amazon",                    7_720_123, "Corporate",     "produce,packaged,meat,dairy,baked"),
    ("Hunts Point Produce Market",3_360_391, "Hunts Point",   "produce"),
    ("Baldor Specialty Foods",    2_735_367, "Wholesale",     "produce,meat,dairy,packaged"),
    ("Trader Joe's",              2_673_191, "Supermarkets",  "produce,meat,dairy,packaged,baked"),
    ("FreshDirect",               2_522_874, "Supermarkets",  "packaged,produce,baked,dairy"),
    ("Whole Foods Market",        1_368_433, "Supermarkets",  "produce,packaged,dairy,baked,meat"),
    ("Jacob's Village Farm",      1_202_662, "Wholesale",     "produce"),
    ("Costco",                      691_800, "Supermarkets",  "produce,meat,dairy,packaged,baked"),
    ("BJ's Wholesale Club",         579_885, "Supermarkets",  "produce,meat,dairy,packaged,baked"),
    ("GrowNYC Greenmarket",         449_493, "Greenmarket",   "produce"),
    ("4C Foods",                    441_037, "Manufacturers", "packaged"),
    ("Pret A Manger",               323_093, "Quickservice",  "prepared,salads,snacks"),
]

# ---------------------------------------------------------------------------
# Tier B -- the 15 category rosters (named, NO published amount)
# ---------------------------------------------------------------------------
# Verbatim from the City Harvest page info-lists section.
ROSTER = {
    "Bakery": [
        "New Yorker Wholesale Bagels", "Leaven & Co./RM Bakery",
        "All Natural Products", "Tom Cat Bakery", "Black Seed Bagels LLC",
    ],
    "Caterer": [
        "Cultivated", "Hello Fresh", "Worlds Fair Marina Restaurant & Banquet",
        "Do & Co. Catering NY", "Borenstein Caterers, Inc.",
    ],
    "Corporate": [
        "Amazon", "Compass Group", "GoPuff",
        "MSC Mediterranean Shipping Company (USA) Inc.", "GiveHealthy",
    ],
    "Farms": [
        "Nash Produce", "Jackson Farming Co.", "United Apple Sales LLC",
        "Williams Farms LLC", "Rogers Orchards Inc",
    ],
    "Greenmarket": [
        "GrowNYC Union Square Greenmarket", "GrowNYC Grand Army Plaza Greenmarket",
        "GrowNYC 175th Street Greenmarket", "GrowNYC 77th Street Greenmarket",
        "GrowNYC Fort Greene Park Greenmarket",
    ],
    "Hunts Point": [
        "D'Arrigo Brothers", "Nathel & Nathel", "S. Katzman Produce Inc.",
        "Erasmo Armata Inc.", "FresCo",
    ],
    "Manufacturers": [
        "4C Food Corporation", "Coca-Cola North America", "Bimbo Bakeries",
        "ConAgra", "Water Lilies Food Inc.",
    ],
    "Nonprofit & Gov": [
        "Sharing Excess", "Tenmile Farm Foundation", "FarmLink",
        "Rethink Food", "Baby2Baby",
    ],
    "Quickservice": [
        "Pret A Manger (USA) Ltd.", "Paris Baguette", "Bergen Bagels",
        "Bayside Bagels & Deli", "Dunkin' Donuts",
    ],
    "Religious": [
        "East End Temple, Food For Families", "Temple Emanu-El of New York",
        "Congregation Rodeph Sholom", "Chabad of Tribeca (Soho)", "St. James' Church",
    ],
    "Restaurants": [
        "Union Square Events", "The Capital Grille", "Le Bernardin",
        "John's of Times Square", "AMMA Fresh Greek",
    ],
    "Special Events": [
        "US Hunger", "New York Road Runners", "Canstruction",
        "The New York Produce Show and Conference",
        "Associated Supermarket Group Food Show",
    ],
    "Supermarkets": [
        "Trader Joe's", "FreshDirect", "Whole Foods Market, Inc.",
        "Costco", "BJ's Wholesale Club",
    ],
    "Wholesale": [
        "Baldor Specialty Foods", "Jacob's Village Farm Corp.",
        "Zhong Xing Produce Inc", "Citrus World", "Dairyland/The Chef's Warehouse",
    ],
    "Hotels": [
        "Marriott", "Baccarat Hotel", "Wyndham",
        "The New York Edition Hotel", "The Four Seasons Hotel New York",
    ],
}

# ---------------------------------------------------------------------------
# De-duplication / aggregation policy  (writeup S1.2)
# ---------------------------------------------------------------------------
# Some Tier-A anchors are AGGREGATES whose member firms appear in the roster:
#   * "GrowNYC Greenmarket" (449,493 lbs) aggregates the 5 named GrowNYC markets.
#   * "Hunts Point Produce Market" (3.36M lbs) is the market whose 5 named
#     merchants (D'Arrigo, Nathel, Katzman, Armata, FresCo) operate *within* it.
# To avoid double counting we FOLD these member categories into their Tier-A
# aggregate: their roster members are excluded from the additive Tier-B mass.
FOLDED_INTO_AGGREGATE = {"Greenmarket", "Hunts Point"}

# Roster names that are themselves Tier-A anchors (already carry a published
# amount) and so must not be re-counted in Tier B.
KNOWN_NAMES = {d[0] for d in KNOWN_DONORS}
# Normalised aliases linking roster spellings to Tier-A names.
ROSTER_TO_KNOWN_ALIASES = {
    "Whole Foods Market, Inc.": "Whole Foods Market",
    "Pret A Manger (USA) Ltd.": "Pret A Manger",
    # formerly-unnamed anchors, now identified -> drop from Tier B estimation
    "Jacob's Village Farm Corp.": "Jacob's Village Farm",
    "4C Food Corporation": "4C Foods",
}


def build_tier_b():
    """Return Tier-B donor records: named, no published amount, de-duplicated.

    A record is dict(name, category). Excludes: (a) roster names that are
    Tier-A anchors, (b) categories folded into an aggregate anchor.
    """
    tier_b = []
    for cat, names in ROSTER.items():
        if cat in FOLDED_INTO_AGGREGATE:
            continue
        for n in names:
            canonical = ROSTER_TO_KNOWN_ALIASES.get(n, n)
            if canonical in KNOWN_NAMES:
                continue  # already a Tier-A anchor with a published amount
            tier_b.append({"name": n, "category": cat})
    return tier_b


if __name__ == "__main__":
    tb = build_tier_b()
    a_total = sum(d[1] for d in KNOWN_DONORS)
    print(f"Tier A: {len(KNOWN_DONORS)} donors, {a_total:,} lbs published")
    print(f"Tier B: {len(tb)} named donors w/o amounts (post de-dup/fold)")
    from collections import Counter
    print("Tier B by category:", dict(Counter(d['category'] for d in tb)))
