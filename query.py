from __future__ import annotations

import json
import sys
import traceback
from functools import reduce
from pathlib import Path
from typing import Annotated, Any, AsyncGenerator, Awaitable, Callable

import litellm
import pandas as pd

from tool import Toolbox

# Available models:
#
# gpt-4o-mini (recommended)
# gpt-4o
# claude-3-5-sonnet-20240620 (recommended)
# Llama3-8b-8192
# Llama-3.1-8b-Instant
# Llama-3.1-70b-Versatile
# Mixtral-8x7b-32768

default_model = "gpt-4o-mini"

# litellm.set_verbose = True


def system_prompt(
    df: pd.DataFrame, name: str, categorical_threshold: int = 10
) -> object:
    schema = df_to_schema(df, name, categorical_threshold)
    with open(Path(__file__).parent / "prompt.md", "r") as f:
        rendered_prompt = f.read().replace("${SCHEMA}", schema)
        return {"role": "system", "content": rendered_prompt}


async def perform_query(
    messages,
    user_input,
    *,
    model: str | None = None,
    model_kwargs: dict[str, Any] = {},
    toolbox: Toolbox | None = None,
) -> AsyncGenerator[dict, None]:

    if model is None:
        model = default_model

    messages.append({"role": "user", "content": user_input})

    print(f"Using {model}")

    while True:
        try:
            stream = await litellm.acompletion(
                model,
                [*messages],
                tools=toolbox.schema if toolbox is not None else None,
                **model_kwargs,
                stream=True,
            )
            chunks = []
            async for chunk in stream:
                print({k: v for k, v in chunk.choices[0].delta.dict().items() if v is not None})
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.dict()
                chunks.append(chunk)
        except Exception as e:
            print(messages[1:])
            raise


        response = litellm.stream_chunk_builder(chunks)
        # print(response)

        if (
            response.choices[0].finish_reason == "tool_calls"
            and len(response.choices[0].message.tool_calls) == 0
        ):
            print("No tool calls!! Retrying...", file=sys.stderr)
            yield {"role": "assistant", "content": f"\n\n**Error**: {e}"}
            continue

        # print(response.choices[0].messages.to_dict())
        messages.append(response.choices[0].message.to_dict())

        try:
            finish_reason = response.choices[0].finish_reason
            if finish_reason == "tool_calls":
                for tool_call in response.choices[0].message.tool_calls:
                    messages.append(await toolbox(tool_call))
            elif finish_reason == "content_filter":
                yield {
                    "role": "assistant",
                    "content": f"\n\n**Error**: The assistant's content moderation filter has been triggered",
                }
                return
            elif finish_reason == "length":
                yield {
                    "role": "assistant",
                    "content": f"\n\n**Error**: The assistant's output token limit has been reached",
                }
                return
            elif finish_reason in [
                "stop",
            ]:
                return
            else:
                raise RuntimeError(
                    f"Unexpected result received from assistant: unrecognized finish_reason '{response.finish_reason}'"
                )
        except Exception as e:
            # This is for truly unexpected exceptions; for exceptions in the
            # tools themselves, the decorator will wrap them

            print(response, file=sys.stderr)
            traceback.print_exception(e)
            yield {"role": "assistant", "content": f"\n\n**Error**: {e}"}
            return

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
