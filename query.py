from __future__ import annotations

import json
import os
from pathlib import Path

import dotenv
from openai import AsyncOpenAI

dotenv.load_dotenv()
if os.environ.get("OPENAI_API_KEY") is None:
    raise ValueError("OPENAI_API_KEY not found in .env file")

client = AsyncOpenAI()

with open(Path(__file__).parent / "prompt.md", "r") as f:
    system_prompt = {"role": "system", "content": f.read()}


async def perform_query(messages: list[dict[str, str]]) -> tuple[str, str | None]:
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.7,
        response_format={"type": "json_object"},
    )
    response_text = response.choices[0].message.content
    print(response_text)
    try:
        response_obj = json.loads(response_text)
    except:
        raise RuntimeError("Unexpected result received from model; invalid JSON")

    if "response" in response_obj and "sql" in response_obj and "title" in response_obj:
        return response_obj["response"], response_obj["sql"], response_obj["title"]
    if "error" in response_obj:
        return response_obj["error"], None, None

    raise RuntimeError(
        "Unexpected result received from model; JSON was not in correct format"
    )
