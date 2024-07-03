from pathlib import Path

import duckdb
import pandas as pd

app_dir = Path(__file__).parent
tips = pd.read_csv(app_dir / "tips.csv")
duckdb.register("tips", tips)
