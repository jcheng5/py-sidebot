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

client = AsyncOpenAI(base_url="http://localhost:11434/v1")


def system_prompt(
    df: pd.DataFrame, name: str, categorical_threshold: int = 10
) -> dict[str, str]:
    schema = df_to_schema(df, name, categorical_threshold)
    with open(Path(__file__).parent / "prompt.md", "r") as f:
        return {"role": "system", "content": f.read().replace("${SCHEMA}", schema)}


async def perform_query(
    messages,
    query_db: Callable[[str], str],
    *,
    model: str = "mistral",
    progress_callback: Callable[[str], None] = lambda x: None,
) -> tuple[str, str | None, str | None]:
    messages = [*messages]

    query_result = None
    title_result = None

    def update_dashboard(query, title):
        nonlocal query_result
        nonlocal title_result
        query_result = query
        title_result = title
        return json.dumps(None)

    tools = {"query": query_db, "update_dashboard": update_dashboard}

    while True:
        progress_callback("Thinking...")
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7,
            tools=[query_tool_definition, update_dashboard_tool_definition],
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

                    if not tool_call.function.name in tools:
                        raise RuntimeError(
                            f"Unexpected result received from model: unknown tool '{tool_call.function.name}' called"
                        )

                    kwargs = json.loads(tool_call.function.arguments)
                    json_response = tools[tool_call.function.name](**kwargs)
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
                response_md = response.choices[0].message.content
                if query_result is not None:
                    response_md += f"\n\n```sql\n{query_result}\n```\n"
                return response_md, query_result, title_result

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

update_dashboard_tool_definition = {
    "function": {
        "name": "update_dashboard",
        "description": "Modifies the data presented in the data dashboard, based on the given SQL query, and also updates the title.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A DuckDB SQL query; must be a SELECT statement.",
                },
                "title": {
                    "type": "string",
                    "description": "A title to display at the top of the data dashboard, summarizing the intent of the SQL query.",
                },
            },
            "required": ["query", "title"],
        },
    },
    "type": "function",
}
