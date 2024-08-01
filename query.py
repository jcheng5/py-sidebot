from __future__ import annotations

import functools
import sys
import traceback
from pathlib import Path
from typing import Annotated, Awaitable, Callable

import pandas as pd
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool

import models

# Available models:
#
# gpt-4o-mini (recommended)
# gpt-4o
# claude-3-5-sonnet-20240620 (recommended)
# Llama3-8b-8192
# Llama-3.1-8b-Instant
# Llama-3.1-70b-Versatile

llm = models.get_model("gpt-4o-mini")


def system_prompt(
    df: pd.DataFrame, name: str, categorical_threshold: int = 10
) -> SystemMessage:
    schema = df_to_schema(df, name, categorical_threshold)
    with open(Path(__file__).parent / "prompt.md", "r") as f:
        rendered_prompt = f.read().replace("${SCHEMA}", schema)
        return SystemMessage(rendered_prompt)


def safe_tool(fn):
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            traceback.print_exc()
            return {"success": False, "error": str(e)}

    return tool(wrapper)


async def perform_query(
    messages,
    user_input,
    *,
    query_db: Callable[[str], Awaitable[str]],
    update_filter: Callable[[str, str], Awaitable[None]],
    model: str = "",
    progress_callback: Callable[[str], None] = lambda x: None,
) -> tuple[str, str | None, str | None]:

    @safe_tool
    async def update_dashboard(
        query: Annotated[str, "A DuckDB SQL query; must be a SELECT statement."],
        title: Annotated[
            str,
            "A title to display at the top of the data dashboard, summarizing the intent of the SQL query.",
        ],
    ):
        """Modifies the data presented in the data dashboard, based on the given SQL query, and also updates the title."""

        # Verify that the query is OK; throws if not
        await query_db(query)

        await update_filter(query, title)

    @safe_tool
    async def reset_dashboard():
        """Resets the filter/sort and title of the data dashboard back to its initial state."""
        await update_filter("", "")

    @safe_tool
    async def query(
        query: Annotated[str, "A DuckDB SQL query; must be a SELECT statement."]
    ):
        """Perform a SQL query on the data, and return the results as JSON."""
        progress_callback("Querying database...")
        return await query_db(query)

    tools = [update_dashboard, reset_dashboard, query]
    tools_by_name = {tool.name: tool for tool in tools}
    llm_with_tools = llm.bind_tools(tools)

    messages.append(HumanMessage(user_input))

    while True:
        progress_callback("Thinking...")
        stream = llm_with_tools.astream(messages)

        response = None
        async for chunk in stream:
            print(chunk.to_json())
            if chunk.content:
                # normalize_content is a workaround; it's necessary because
                # Shiny 1.0.0's ui.Chat component isn't compatible with the
                # shape of the content coming back from Anthropic (specifically).
                # Shiny expects content to be str, instead it's more like:
                # [{"type": "text", "text": "blah blah blah"}]
                #
                # If/when ui.Chat is fixed, this can just be `yield chunk`.
                yield {
                    "role": "assistant",
                    "content": normalize_content(chunk.content),
                }
            if response is None:
                response = chunk
            else:
                response += chunk

        messages.append(response)

        try:
            if len(response.tool_calls) > 0:
                for tool_call in response.tool_calls:
                    messages.append(
                        await tools_by_name[tool_call["name"]].ainvoke(tool_call)
                    )
            else:
                return

            # else:
            #     raise RuntimeError(
            #         f"Unexpected result received from model: unrecognized finish_reason '{response.finish_reason}'"
            #     )
        except Exception as e:
            print(response, file=sys.stderr)
            traceback.print_exception(e)
            messages.append(AIMessage(f"**Error**: {e}"))
            return
            # return f"**Error:** {e}", None, None

        # Add newlines between responses
        yield {"role": "assistant", "content": "\n\n"}


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


def normalize_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(normalize_content(x) for x in content)
    if isinstance(content, dict):
        if "type" in content and content["type"] == "text":
            return content.get("text", "")
        return ""
    return ""
