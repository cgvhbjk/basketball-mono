"""
247Sports recruiting profile extractor.

Compliance-first: respects robots.txt (which Disallows *.json), throttles to
~0.2 rps per host, caches GETs on disk, and never bypasses access controls.
Use the offline `parse` CLI subcommand for any URL that robots disallows —
do not work around the guard.
"""
