import copy
import importlib.util
import unittest
from datetime import date
from pathlib import Path

spec = importlib.util.spec_from_file_location("political_macro", Path(__file__).resolve().parents[1] / "ops" / "political_macro.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def sample():
    return {"country":"ES", "event":"議会", "observed_at":"2026-11-26T10:00:00+09:00", "records":[{"label":"FACT", "topic":"election", "kind":"official_certified", "text":"結果", "source_url":"https://example.gov/election", "published_at":"2026-11-25T10:00:00+09:00", "election":{"total_seats":350,"party_seats":170,"threshold_rule":"absolute_total_seats"}}]}

class TestPoliticalMacro(unittest.TestCase):
    def test_legal_threshold(self):
        self.assertIn("176議席", m.render(sample(), date(2026,11,26)))
        self.assertIn("不足：6議席", m.render(sample(), date(2026,11,26)))
    def test_future_information_rejected(self):
        d=sample(); d["records"][0]["published_at"]="2026-11-26T11:00:00+09:00"
        with self.assertRaises(ValueError): m.validate(d)
    def test_poll_is_not_official_result(self):
        d=sample(); d["records"][0]["kind"]="poll"
        with self.assertRaises(ValueError): m.validate(d)
    def test_intraday_rejected(self):
        d=sample(); d["records"]=[{"label":"FACT","topic":"market","kind":"daily_market","text":"price","source_url":"https://example.gov/p","published_at":None,"market_date":"2026-11-25","instrument":"EURUSD","unit":"USD","value":1,"frequency":"hourly"}]
        with self.assertRaises(ValueError): m.validate(d)
    def test_cross_country_comparison_rejected(self):
        d=sample(); old=copy.deepcopy(d); old["country"]="US"; old["observed_at"]="2026-11-25T11:00:00+09:00"
        with self.assertRaises(ValueError): m.render(d,date(2026,11,26),old)

if __name__ == "__main__": unittest.main()
