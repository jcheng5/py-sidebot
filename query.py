from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import dotenv
import pandas as pd
from openai import AsyncOpenAI

dotenv.load_dotenv()
if os.environ.get("OPENAI_API_KEY") is None:
    raise ValueError("OPENAI_API_KEY not found in .env file")

client = AsyncOpenAI()


def system_prompt(
    df: pd.DataFrame, name: str, categorical_threshold: int = 10
) -> dict[str, str]:
    schema = df_to_schema(df, name, categorical_threshold)
    with open(Path(__file__).parent / "prompt.md", "r") as f:
        return {"role": "system", "content": f.read().replace("${SCHEMA}", schema)}


async def perform_query(messages: list[dict[str, str]]) -> tuple[str, str | None]:
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.7,
        response_format={"type": "json_object"},
    )
    response_text = response.choices[0].message.content
    try:
        response_obj = json.loads(response_text)
    except:
        raise RuntimeError("Unexpected result received from model; invalid JSON")

    if "response" in response_obj and "sql" in response_obj and "title" in response_obj:
        return response_obj["response"], response_obj["sql"], response_obj["title"]
    if "error" in response_obj:
        return response_obj["error"], None, None
    print(response_text, file=sys.stderr)
    raise RuntimeError(
        "Unexpected result received from model; JSON was not in correct format"
    )


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

    return "\n".join(schema)
