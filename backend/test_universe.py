import unittest
from unittest.mock import patch

import pandas as pd

import universe


class RussellUniverseTests(unittest.TestCase):
    def test_parse_blackrock_iwm_payload(self):
        payload = {
            "componentsByNameMap": {
                "holdings": {
                    "containersByNameMap": {
                        "all": {
                            "dataPointsByNameMap": {
                                "ticker": {"value": ["ABC", "BRK.B", "USD"]},
                                "issueName": {"value": ["ABC Corp", "Berkshire", "Cash"]},
                                "sectorName": {
                                    "value": ["Industrials", "Financials", None]
                                },
                                "assetClass": {"value": ["Equity", "Equity", "Cash"]},
                            }
                        }
                    }
                }
            }
        }

        holdings = universe._parse_iwm_holdings_payload(payload)

        self.assertEqual([item["symbol"] for item in holdings], ["ABC", "BRK-B"])
        self.assertTrue(all(item["source"] == "russell2000" for item in holdings))

    def test_parse_iwm_holdings_skips_non_equities_and_normalizes_symbols(self):
        payload = """Fund Holdings as of,Jun 08 2026
Ticker,Name,Sector,Asset Class
ABC,ABC Corporation,Industrials,Equity
BRK.B,Berkshire Hathaway,Financials,Equity
USD,US Dollar,Cash and/or Derivatives,Cash
"""

        holdings = universe._parse_iwm_holdings_csv(payload)

        self.assertEqual([item["symbol"] for item in holdings], ["ABC", "BRK-B"])
        self.assertTrue(all(item["source"] == "russell2000" for item in holdings))

    @patch("universe._latest_daily_volumes")
    def test_liquid_selection_removes_overlaps_before_volume_fetch(self, volume_mock):
        holdings = [
            {
                "symbol": f"R{i:03d}",
                "name": f"Russell {i}",
                "sector": "Industrials",
                "source": "russell2000",
            }
            for i in range(160)
        ]
        holdings.append(dict(holdings[10]))
        excluded = {"R000", "R001", "R002"}
        volume_mock.side_effect = lambda symbols: {
            symbol: float(1_000_000 - index)
            for index, symbol in enumerate(symbols)
        }

        selected = universe._select_liquid_russell(holdings, excluded, limit=125)

        fetched_symbols = volume_mock.call_args.args[0]
        self.assertTrue(excluded.isdisjoint(fetched_symbols))
        self.assertEqual(len(fetched_symbols), len(set(fetched_symbols)))
        self.assertEqual(len(selected), 125)
        self.assertTrue(excluded.isdisjoint(item["symbol"] for item in selected))
        self.assertGreaterEqual(
            selected[0]["daily_volume"],
            selected[-1]["daily_volume"],
        )

    @patch("universe.yf.download")
    def test_volume_downloads_never_exceed_fifty_symbols(self, download_mock):
        calls: list[int] = []

        def fake_download(symbols, **_kwargs):
            calls.append(len(symbols))
            dates = pd.date_range("2026-06-08", periods=2)
            columns = pd.MultiIndex.from_product(
                [symbols, ["Open", "High", "Low", "Close", "Volume"]]
            )
            frame = pd.DataFrame(1.0, index=dates, columns=columns)
            for index, symbol in enumerate(symbols):
                frame.loc[:, (symbol, "Volume")] = [100 + index, 200 + index]
            return frame

        download_mock.side_effect = fake_download
        symbols = [f"R{i:03d}" for i in range(123)]

        volumes = universe._latest_daily_volumes(symbols, batch_size=500)

        self.assertEqual(calls, [50, 50, 23])
        self.assertEqual(len(volumes), 123)
        self.assertTrue(all(size <= 50 for size in calls))


if __name__ == "__main__":
    unittest.main()
