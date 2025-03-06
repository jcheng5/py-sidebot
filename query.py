from __future__ import annotations

from pathlib import Path

import pandas as pd

# Available models:
#
# gpt-4o-mini (recommended)
# gpt-4o
# claude-3-5-sonnet-20240620 (recommended)
# Llama3-8b-8192
# Llama-3.1-8b-Instant
# Llama-3.1-70b-Versatile
# Mixtral-8x7b-32768

default_model = "o3-mini"


def system_prompt(df: pd.DataFrame, name: str, categorical_threshold: int = 10) -> str:
    schema = df_to_schema(df, name, categorical_threshold)
    with open(Path(__file__).parent / "prompt.md", "r") as f:
        rendered_prompt = f.read().replace("${SCHEMA}", schema)
        return rendered_prompt


def df_to_schema(df: pd.DataFrame, name: str, categorical_threshold: int):
    schema = []
    schema.append(f"Table: {name}")
    schema.append("Columns:")

    for column, dtype in df.dtypes.items():
        # Map pandas dtypes to SQL-like types
        if pd.api.types.is_integer_dtype(dtype):
            sql_type = "INTEGER"
        elif pd.api.types.is_float_dtype(dtype):
            sql_type = "FLOAT"
        elif pd.api.types.is_bool_dtype(dtype):
            sql_type = "BOOLEAN"
        elif pd.api.types.is_datetime64_any_dtype(dtype):
            sql_type = "DATETIME"
        else:
            sql_type = "TEXT"

        schema.append(f"- {column} ({sql_type})")

        # For TEXT columns, check if they're categorical
        if sql_type == "TEXT":
            unique_values = df[column].nunique()
            if unique_values <= categorical_threshold:
                categories = df[column].unique().tolist()
                categories_str = ", ".join(f"'{cat}'" for cat in categories)
                schema.append(f"  Categorical values: {categories_str}")
        # For FLOAT and INTEGER columns, add the range
        elif sql_type in ["INTEGER", "FLOAT"]:
            min_val = df[column].min()
            max_val = df[column].max()
            schema.append(f"  Range: {min_val} to {max_val}")

    return "\n".join(schema)
