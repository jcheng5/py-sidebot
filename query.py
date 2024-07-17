from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Callable

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


async def perform_query(
    messages,
    query_db: Callable[[str], str],
    progress_callback: Callable[[str], None] = lambda x: None,
) -> tuple[str, str | None, str | None]:
    messages = [*messages]
    while True:
        progress_callback("Thinking...")
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.7,
            response_format={"type": "json_object"},
            tools=[query_tool_definition],
        )

        try:
            # print(response)
            if (
                response.choices[0].finish_reason == "tool_calls"
                and response.choices[0].message.tool_calls
            ):
                tool_responses = []
                for tool_call in response.choices[0].message.tool_calls:
                    progress_callback("Querying database...")
                    if tool_call.function.name != "query":
                        raise RuntimeError(
                            f"Unexpected result received from model: unknown tool '{tool_call.function.name}' called"
                        )
                    args = json.loads(tool_call.function.arguments)
                    if "query" not in args:
                        raise RuntimeError(
                            "Unexpected result received from model: query was called, but required argument(s) not found"
                        )
                    json_response = query_db(args["query"])
                    tool_responses.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.function.name,
                            "content": json_response,
                        }
                    )
                messages.append(response.choices[0].message)
                messages.extend(tool_responses)

            # end_turn is what OpenRouter.ai/Anthropic returns through the openai client
            elif response.choices[0].finish_reason in ["stop", "length", "end_turn"]:
                response_text = response.choices[0].message.content
                try:
                    response_obj = json.loads(response_text)
                except:
                    raise RuntimeError(
                        "Unexpected result received from model; invalid JSON"
                    )

                response_type = (
                    response_obj["response_type"]
                    if "response_type" in response_obj
                    else None
                )

                if response_type == "select":
                    return (
                        response_obj["response"],
                        response_obj["sql"],
                        response_obj["title"],
                    )
                elif response_type == "answer":
                    return response_obj["response"], None, None
                elif response_type == "error":
                    return response_obj["response"], None, None
                else:
                    raise RuntimeError(
                        "Unexpected result received from model: JSON was not in correct format"
                    )
            else:
                raise RuntimeError(
                    f"Unexpected result received from model: unrecognized finish_reason '{response.choices[0].finish_reason}'"
                )
        except Exception as e:
            print(response.choices[0].message, file=sys.stderr)
            traceback.print_exception(e)
            return f"**Error:** {e}", None, None


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

query_tool_definition = {
    "function": {
        "name": "query",
        "description": "Perform a SQL query on the data, and return the results as JSON.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A DuckDB SQL query; must be a SELECT statement.",
                }
            },
            "required": ["query"],
        },
    },
    "type": "function",
}
