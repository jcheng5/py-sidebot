from pathlib import Path

import duckdb
import pandas as pd

duckdb.query("SET allow_community_extensions = false;")

here = Path(__file__).parent
tips = pd.read_csv(here / "tips.csv")
tips["percent"] = tips.tip / tips.total_bill

duckdb.register("tips", tips)
