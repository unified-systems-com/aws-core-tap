"""The AWS coverage ledger: every in-scope AWS resource type and what aws_core does with it.

Spec: ``specs/spec-aws-core-coverage-ledger.md``. The ledger joins **facts** derived from AWS's own
machine-readable models (``sources.py``) with **decisions** a reviewer committed (``decisions.json``), so
"full AWS coverage" is a count of unclassified rows that can be driven to zero. ``python -m
tap_plugin.aws_core.ledger`` builds, checks and fetches; nothing here imports Django.
"""
