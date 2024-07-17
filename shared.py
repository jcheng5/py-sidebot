from pathlib import Path

import duckdb
import pandas as pd

app_dir = Path(__file__).parent
tips = pd.read_csv(app_dir / "tips.csv")
tips["percent"] = tips.tip / tips.total_bill

duckdb.register("tips", tips)
