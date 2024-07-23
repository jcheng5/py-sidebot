from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Callable

import dotenv
import pandas as pd
from anthropic import NOT_GIVEN, AsyncAnthropic

dotenv.load_dotenv()
if os.environ.get("ANTHROPIC_API_KEY") is None:
    raise ValueError("ANTHROPIC_API_KEY not found in .env file")

client = AsyncAnthropic()


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
    model: str = "claude-3-5-sonnet-20240620",
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

    system_message = NOT_GIVEN
    if messages[0]["role"] == "system":
        system_message = messages.pop(0)["content"]

    while True:
        progress_callback("Thinking...")
        # print("--------")
        # print(messages)
        response = await client.messages.create(
            model=model,
            system=system_message,
            messages=messages,
            max_tokens=1024,
            temperature=0.7,
            tools=[query_tool_definition, update_dashboard_tool_definition],
        )

        try:
            print(response)
            if response.stop_reason == "tool_use":
                tool_calls = [c for c in response.content if c.type == "tool_use"]
                tool_responses = []
                for tool_call in tool_calls:
                    progress_callback("Querying database...")

                    if not tool_call.name in tools:
                        raise RuntimeError(
                            f"Unexpected result received from model: unknown tool '{tool_call.name}' called"
                        )

                    kwargs = tool_call.input
                    json_response = tools[tool_call.name](**kwargs)
                    tool_responses.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_call.id,
                                    "content": json_response,
                                }
                            ],
                        }
                    )
                messages.append({"role": "assistant", "content": response.content})
                messages.extend(tool_responses)

            # end_turn is what OpenRouter.ai/Anthropic returns through the openai client
            elif response.stop_reason in ["stop", "length", "end_turn"]:
                response_md = "\n\n".join([c.text for c in response.content if c.type == "text"])
                return response_md, query_result, title_result

            else:
                raise RuntimeError(
                    f"Unexpected result received from model: unrecognized finish_reason '{response.finish_reason}'"
                )
        except Exception as e:
            print(response, file=sys.stderr)
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
    "name": "query",
    "description": "Perform a SQL query on the data, and return the results as JSON.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "A DuckDB SQL query; must be a SELECT statement.",
            }
        },
        "required": ["query"],
    },
}

update_dashboard_tool_definition = {
    "name": "update_dashboard",
    "description": "Modifies the data presented in the data dashboard, based on the given SQL query, and also updates the title.",
    "input_schema": {
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
}
