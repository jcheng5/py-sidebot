from pathlib import Path

import duckdb
import pandas as pd

import query

duckdb.query("SET allow_community_extensions = false;")

here = Path(__file__).parent
birds = pd.read_csv(here / "alabama_birds_demo.csv")
birds["time"] = pd.to_datetime(birds["date"] + "T" + birds["time"], format="ISO8601")
birds.drop(columns=["date"], inplace=True)

duckdb.register("birds", birds)

species_csv = (
    birds[["bird_name", "scientific_name"]].drop_duplicates().to_csv(index=False)
)

birds_system_prompt = (
    query.system_prompt(birds, "birds")
    + f"\n\nHere is a list of all available birds in the dataset:\n\n{species_csv}"
)
