from pathlib import Path

import pandas as pd
import pytest

from goldscalper.data import generate_synthetic, load_csv


def test_load_csv_parses_mt5_style_tab_separated_export(tmp_path: Path):
    # Mirrors MT5's native "Export Bars": tab-separated, <ANGLE BRACKET>
    # headers, separate DATE/TIME columns, tick volume + spread.
    content = (
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
        "2024.01.01\t00:00:00\t2000.10\t2001.50\t1999.80\t2001.00\t120\t0\t25\n"
        "2024.01.01\t01:00:00\t2001.00\t2003.00\t2000.50\t2002.50\t95\t0\t27\n"
    )
    path = tmp_path / "gold_export.csv"
    path.write_text(content)

    df = load_csv(str(path))

    assert list(df.columns) == ["open", "high", "low", "close", "volume", "spread"]
    assert len(df) == 2
    assert df["open"].iloc[0] == pytest.approx(2000.10)
    assert df["spread"].iloc[1] == pytest.approx(27.0)
    assert df["volume"].iloc[0] == pytest.approx(120.0)  # falls back to tick volume
    assert df.index[0] == pd.Timestamp("2024-01-01 00:00:00")
    assert df.index.is_monotonic_increasing


def test_load_csv_handles_combined_datetime_column(tmp_path: Path):
    content = "datetime,open,high,low,close,volume\n" "2024-01-01 00:00:00,1,2,0.5,1.5,10\n"
    path = tmp_path / "simple.csv"
    path.write_text(content)
    df = load_csv(str(path))
    assert len(df) == 1
    assert df.index[0] == pd.Timestamp("2024-01-01")


def test_load_csv_deduplicates_keeping_the_last_occurrence(tmp_path: Path):
    content = (
        "datetime,open,high,low,close,volume\n"
        "2024-01-01 00:00:00,1,2,0.5,1.5,10\n"
        "2024-01-01 00:00:00,9,9,9,9,9\n"
    )
    path = tmp_path / "dup.csv"
    path.write_text(content)
    df = load_csv(str(path))
    assert len(df) == 1
    assert df["open"].iloc[0] == 9  # last occurrence wins


def test_load_csv_raises_on_missing_required_columns(tmp_path: Path):
    content = "datetime,open,high\n2024-01-01,1,2\n"
    path = tmp_path / "bad.csv"
    path.write_text(content)
    with pytest.raises(ValueError):
        load_csv(str(path))


def test_generate_synthetic_is_deterministic_and_well_formed():
    a = generate_synthetic(n_bars=200, seed=7)
    b = generate_synthetic(n_bars=200, seed=7)
    pd.testing.assert_frame_equal(a, b)

    assert len(a) == 200
    assert (a["high"] >= a[["open", "close"]].max(axis=1)).all()
    assert (a["low"] <= a[["open", "close"]].min(axis=1)).all()
    assert (a["close"] > 0).all()
