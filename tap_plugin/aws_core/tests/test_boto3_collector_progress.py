"""Interim progress lines (req-aws-collector-progress): throttled, counts only, and written by a real run."""

from __future__ import annotations

import logging
import re

import pytest
from tap_plugin.aws_core.collectors.boto3_collector.progress import Progress

ENTRY = {"service": "ec2", "entity_type": "aws_core__aws_vpc"}


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _progress(total=10, interval=30.0):
    lines: list[str] = []
    clock = _Clock()
    progress = Progress(total, interval=interval, clock=clock, emit=lambda fmt, *a: lines.append(fmt % a))
    return progress, clock, lines


class TestProgress:
    @pytest.mark.spec("req-aws-collector-progress-2")
    def test_a_fast_run_writes_no_heartbeat(self):
        progress, clock, lines = _progress()
        for done in range(10):
            clock.now += 1
            progress.tick(done, ENTRY, nodes=done, edges=0)
        assert lines == []

    @pytest.mark.spec("req-aws-collector-progress-2")
    def test_a_slow_run_writes_one_line_per_interval_naming_the_entry_and_counts(self):
        progress, clock, lines = _progress(total=10, interval=30)
        progress.tick(1, ENTRY, nodes=5, edges=2)
        clock.now += 31
        progress.tick(2, ENTRY, nodes=7, edges=3)
        clock.now += 10
        progress.tick(3, ENTRY, nodes=9, edges=4)
        assert len(lines) == 1
        assert "2/10 entries (20%)" in lines[0] and "ec2:vpc" in lines[0]
        assert "7 nodes and 3 edges" in lines[0] and "31s elapsed" in lines[0]

    @pytest.mark.spec("req-aws-collector-progress-1")
    def test_start_and_end_lines_carry_counts_and_the_selection_note(self):
        progress, clock, lines = _progress(total=4)
        progress.start(regions=2, partition="aws-us-gov", selected_run=True)
        clock.now += 65
        progress.reads_finished(nodes=3, edges=1)
        progress.finished(batches_imported=1)
        assert "4 manifest entries across 2 region(s) in partition aws-us-gov (a selection is applied)" in lines[0]
        assert "after 65s; submitting 3 nodes and 1 edges" in lines[1]
        assert "finished after 65s: 1 batch(es) imported" in lines[2]

    def test_an_empty_manifest_does_not_divide_by_zero(self):
        progress, clock, lines = _progress(total=0, interval=0)
        progress.tick(0, ENTRY, nodes=0, edges=0)
        assert "(100%)" in lines[0]


@pytest.mark.django_db
class TestProgressInARealRun:
    @pytest.mark.spec("req-aws-collector-progress-1")
    @pytest.mark.spec("req-aws-collector-progress-3")
    def test_a_run_writes_its_start_end_and_no_account_number(self, monkeypatch, caplog):
        from tap_plugin.aws_core.tests import test_boto3_collector_selection_run as base

        base._install(monkeypatch, include_types=["ec2:vpc"])
        with caplog.at_level(logging.INFO, logger="tap_plugin.aws_core.collectors.boto3_collector.progress"):
            base._run()
        messages = [r.getMessage() for r in caplog.records]
        assert any("collection started" in m and "(a selection is applied)" in m for m in messages)
        assert any("reads finished" in m for m in messages)
        assert any("collection finished" in m and "1 batch(es) imported" in m for m in messages)
        assert not [m for m in messages if re.search(r"\b\d{12}\b", m)], "a progress line never carries an account number"
