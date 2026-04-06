from math_agent.context.diminishing import DiminishingReturnsDetector, ProgressEntry

class TestDiminishing:
    def test_no_abandon_with_progress(self):
        d = DiminishingReturnsDetector(window=3)
        d.record(ProgressEntry(1, 0, True, True))
        d.record(ProgressEntry(2, 1, True, True))
        d.record(ProgressEntry(3, 2, True, True))
        assert not d.should_abandon()

    def test_abandon_after_stale_window(self):
        d = DiminishingReturnsDetector(window=3)
        d.record(ProgressEntry(1, 1, True, True))
        d.record(ProgressEntry(2, 1, False, False))
        d.record(ProgressEntry(3, 1, False, False))
        d.record(ProgressEntry(4, 1, False, False))
        assert d.should_abandon()

    def test_not_enough_history(self):
        d = DiminishingReturnsDetector(window=3)
        d.record(ProgressEntry(1, 0, False, False))
        assert not d.should_abandon()

    def test_reset_clears(self):
        d = DiminishingReturnsDetector(window=2)
        d.record(ProgressEntry(1, 0, False, False))
        d.record(ProgressEntry(2, 0, False, False))
        assert d.should_abandon()
        d.reset()
        assert not d.should_abandon()
