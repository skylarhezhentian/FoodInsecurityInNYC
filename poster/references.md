# Poster reference guide

The numbering below follows the supplied historical poster. Links and
bibliographic details were checked against publishers, authors' institutional
pages, and the named public agencies on 4 October 2026. The poster and its
archived bibliography remain unchanged. This guide verifies the cited sources;
it does not establish the poster's novelty claim or validate its routing model.

## Public context and data

**[1] Poverty Tracker Research Group at Columbia University (2026).**
*The State of Poverty and Disadvantage in New York City*, Volume 8. Robin Hood.
The [report page](https://robinhood.org/reports/poverty-tracker-annual-report-vol-8/)
dates the report to March 2026 and supports the 2.2 million poverty estimate for
2024. Its historical record claim is limited to the Poverty Tracker's observation
period. The publisher's [16 March 2026 release](https://robinhood.org/news/2026-annual-poverty-tracker-report-release/)
also reports the poster's 62% food-shortfall figure in its discussion of SNAP
recipient families. These are contextual survey findings, not model inputs or
outcomes of the routing experiment.

**[2] New York City Council Data Team.** *Emergency Food in NYC*, drawing on
NYC Mayor's Office of Food Policy data. The [Council page](https://council.nyc.gov/data/emergency-food-in-nyc/)
reports neighborhood food-insecurity rates ranging from 5% to 35% and links to
the [Food Policy supply-gap source](https://www.nyc.gov/site/foodpolicy/reports-and-data/supply-gap.page).
The poster's “2026” label should not be read as a verified observation year for
all records: this live page combines different data vintages. File-level inputs
and their retained versions are documented in [data provenance](../data/README.md).

**[4] New York City Human Resources Administration.** *Food Help NYC*.
The [official location finder](https://finder.nyc.gov/foodhelp/locations) is a
dynamic service. Its current page does not certify the historical 528-recipient
or 526-positive-hours counts; those are properties of the retained project
snapshot and filtering, not a claim about today's directory. The “2026” citation
is a project-era reference, not a confirmed release date for every location.

## Methods and prior work

**[3] Wei Luo and Yi Qi (2009).** “An enhanced two-step floating catchment area
(E2SFCA) method for measuring spatial accessibility to primary care physicians.”
*Health & Place*, 15(4), 1100–1107.
[DOI: 10.1016/j.healthplace.2009.06.002](https://doi.org/10.1016/j.healthplace.2009.06.002).
The [author's institutional copy](https://www.niu.edu/landform/papers/jhap741_e2sfca.pdf)
describes distance-decay accessibility for primary care. The project's provider
hours proxy, food-access application, catchment choice, and Gaussian weighting
are modeling choices; the citation does not validate their calibration.

**[5] Marius M. Solomon (1987).** “Algorithms for the Vehicle Routing and
Scheduling Problems with Time Window Constraints.” *Operations Research*,
35(2), 254–265.
[Publisher and DOI: 10.1287/opre.35.2.254](https://pubsonline.informs.org/doi/10.1287/opre.35.2.254).
This is the cited foundation for vehicle routing with time windows and heuristic
solution methods, not evidence that the project's OR-Tools implementation
reproduces Solomon's experiments.

**[6] Ohad Eisenhandler and Michal Tzur (2019 issue; online 2018).**
“The Humanitarian Pickup and Distribution Problem.” *Operations Research*,
67(1), 10–32.
[Publisher and DOI: 10.1287/opre.2018.1751](https://pubsonline.informs.org/doi/10.1287/opre.2018.1751).
The study addresses food-rescue routing and allocation with equity and
effectiveness objectives. The first author's given name is **Ohad**, not
“Omri” as recorded in the archived `ref.bib`. The printed poster uses the correct
surname. The issue is January–February 2019; the publisher records online
publication on 24 October 2018.

**[7] Irem Sengul Orgut, Julie Ivy, Reha Uzsoy, and James R. Wilson (2016 issue;
online 2015).** “Modeling for the equitable and effective distribution of donated
food under capacity constraints.” *IIE Transactions*, 48(3), 252–266.
[Publisher and DOI: 10.1080/0740817X.2015.1063792](https://www.tandfonline.com/doi/abs/10.1080/0740817X.2015.1063792).
This work studies capacity-constrained equitable food allocation, including
uncertain receiving capacities. The fourth author's given name is **James**,
not “Jeffrey” as recorded in the archived `ref.bib`. The article belongs to the
2016 issue and was published online on 29 December 2015.

These references support the project's background and method lineage. They do
not, by themselves, justify the poster's statement that no earlier work places
spatial access inside a routing objective; that would require a broader,
systematic literature comparison.
