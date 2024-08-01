from __future__ import annotations

import functools
import os
import sys
import traceback
from pathlib import Path
from typing import Annotated, Callable

import dotenv
import pandas as pd
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

dotenv.load_dotenv()
if os.environ.get("ANTHROPIC_API_KEY") is None:
    raise ValueError("ANTHROPIC_API_KEY not found in .env file")

llm = ChatOpenAI(model="gpt-4o-mini")

# from langchain_anthropic import ChatAnthropic
# llm = ChatAnthropic(model="claude-3-5-sonnet-20240620")

# from langchain_community.chat_models.llamacpp import ChatLlamaCpp
# llm = ChatLlamaCpp(
#     model_path="Llama-3-Groq-8B-Tool-Use-Q5_K_M.gguf",
#     max_tokens=1024 * 16,
#     n_ctx=1024 * 16,
# )

# from langchain_groq import ChatGroq

# llm = ChatGroq(model="Llama3-8b-8192")
# llm = ChatGroq(model="Llama-3.1-8b-Instant")
# llm = ChatGroq(model="Llama-3.1-70b-Versatile")


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
    query_db: Callable[[str], str],
    *,
    on_update_dashboard: Callable[[str, str], Awaitable[None]],
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
        query_db(query)

        await on_update_dashboard(query, title)

    @safe_tool
    async def reset_dashboard():
        """Resets the filter/sort and title of the data dashboard back to its initial state."""
        await on_update_dashboard("", "")

    @safe_tool
    async def query(
        query: Annotated[str, "A DuckDB SQL query; must be a SELECT statement."]
    ):
        """Perform a SQL query on the data, and return the results as JSON."""
        progress_callback("Querying database...")
        return query_db(query)

    tools = [update_dashboard, reset_dashboard, query]
    tools_by_name = {tool.name: tool for tool in tools}
    llm_with_tools = llm.bind_tools(tools)

    messages.append(HumanMessage(user_input))

    while True:
        progress_callback("Thinking...")
        stream = llm_with_tools.astream(messages)

        response = None
        async for chunk in stream:
            if chunk.content:
                yield chunk
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
