# Historical source snapshot

These six files preserve the source found beside the saved study outputs:
`replicates.py`, `ch_experiment.py`, `pickup_model.py`, `pareto_frontier.py`,
`geo_travel.py`, and `solve_routes_v1.py`. Together they close the local import
dependencies of the replicate harness.

Five files are byte-for-byte copies. In `solve_routes_v1.py`, one optional
borough-basemap path was changed from a machine-specific absolute path to
`research/historical/data/nyc_boroughs.geojson`. That optional map is not included.
`manifest.json` records the original and packaged hashes and this change.

This is an archive, not the default execution path. It retains historical model
behavior and its limitations. The saved results did not record a source revision,
so recovery of these files does not prove they are exactly the revision that
produced every saved solve. The original replicate file does, however, match the
included saved-result file byte for byte.

Running `replicates.py` is an explicit optional research operation: it launches 55
time-limited solves under the default settings, requires an existing cache, and
writes beside the source. Its relative input paths are resolved from the working
directory. Other archived entry points can call OSRM when their cache is absent.
The archive is not run in CI. Wall-clock search
can yield different routes between runs; it does not recreate the historical
served sets bit for bit. Use the repository's documented saved-result analysis
and bounded routing demo for ordinary review.
