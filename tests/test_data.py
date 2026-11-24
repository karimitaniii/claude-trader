import numpy as np
import pandas as pd

import data


def test_known_no_data_tickers_are_not_downloaded(tmp_path, monkeypatch):
    calls = []
    idx = pd.bdate_range("2020-01-01", periods=3)

    def fake_download(tickers, **kw):
        calls.append(list(tickers))
        return pd.concat({"Close": pd.DataFrame(1.0, index=idx, columns=tickers)}, axis=1)

    monkeypatch.setattr(data, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(data.yf, "download", fake_download)
    close = data.load_prices(["AAPL", "XLNX"], refresh=True)
    assert calls == [["AAPL"]]                   # one call, no dead ticker, no retries
    assert close["XLNX"].isna().all()            # still present for coverage reporting
    assert (close["AAPL"] == 1.0).all()
