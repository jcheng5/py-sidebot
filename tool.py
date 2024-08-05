from __future__ import annotations

import inspect
import json
import traceback
from types import NoneType
from typing import (Annotated, Any, Awaitable, Callable, Generic, ParamSpec,
                    TypedDict, TypeVar, get_args, get_origin, get_type_hints,
                    is_typeddict, overload)

from litellm.types.completion import (ChatCompletionMessageToolCallParam,
                                      ChatCompletionToolMessageParam)

__all__ = (
    "tool",
    "WrappedTool",
    "Toolbox",
)

P = ParamSpec("P")
R = TypeVar("R")

JSONifiable = dict | list | str | int | float | bool | None


class Toolbox:
    def __init__(self, *tools: WrappedTool):
        for tool in tools:
            if not isinstance(tool, WrappedTool):
                raise TypeError(
                    "Arguments to Toolbox() must be functions decorated with @tool"
                )
        self.tools = {tool.name: tool for tool in tools}
        self.schema = [tool.schema for tool in tools]

    async def __call__(
        self, tool_call: ChatCompletionMessageToolCallParam
    ) -> ChatCompletionToolMessageParam:
        name = tool_call.function.name
        tool = self.tools.get(name)
        if tool is None:
            await toolinvoke(
                lambda **kwargs: {"success": False, "error": f"Unknown tool: {name}"},
                tool_call,
            )
        return await toolinvoke(tool, tool_call)


class WrappedTool(Generic[P, R], Callable[P, Awaitable[R]]):
    def __init__(self, func: Callable[P, Awaitable[R]], name: str):
        self.func = func
        self.name = name
        self.schema = func_to_schema(func, name)

    async def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        return await self.func(*args, **kwargs)


async def toolinvoke(
    func: Callable[..., Awaitable[Any]], tool_call: ChatCompletionMessageToolCallParam
) -> ChatCompletionToolMessageParam:
    id = tool_call.id
    name = tool_call.function.name
    try:
        kwargs = json.loads(tool_call.function.arguments)
        result = json.dumps(await func(**kwargs))
    except Exception as e:
        traceback.print_exc()
        result = json.dumps(
            {"success": False, "error": str(e), "traceback": traceback.format_exc()}
        )

    return {
        "tool_call_id": id,
        "role": "tool",
        "name": name,
        "content": result,
    }


@overload
def tool(
    func: Callable[P, Awaitable[R]], *, name: str | None = None
) -> WrappedTool[P, R]: ...


@overload
def tool(
    *, name: str | None = None
) -> Callable[[Callable[P, Awaitable[R]]], WrappedTool[P, R]]: ...


def tool(
    func: Callable[P, Awaitable[R]] | None = None, *, name: str | None = None
) -> WrappedTool[P, R] | Callable[[Callable[P, Awaitable[R]]], WrappedTool[P, R]]:
    if func is None:
        return lambda f: tool(f, name=name)

    return WrappedTool(func, name or func.__name__)


def func_to_schema(func: callable, name: str | None = None) -> dict:
    signature = inspect.signature(func)
    required = []

    for nm, param in signature.parameters.items():
        if param.default is param.empty and param.kind not in [
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ]:
            required.append(nm)

    annotations = get_type_hints(func, include_extras=True)

    description = func.__doc__

    return {
        "type": "function",
        "function": {
            "name": name or func.__name__,
            **({} if description is None else {"description": description}),
            "parameters": {
                "type": "object",
                "properties": {
                    k: type_to_json_schema(v, None)
                    for k, v in annotations.items()
                    if k != "return"
                },
                "required": required,
            },
        },
    }


def type_to_json_schema(t: type, desc: str | None = None) -> str:
    origin = get_origin(t)
    args = get_args(t)
    if origin is Annotated:
        assert len(args) == 2
        assert desc is None or desc == ""
        assert isinstance(args[1], str)
        return type_to_json_schema(args[0], args[1])

    if origin is list:
        assert len(args) == 1
        return type_dict("array", desc, items=type_to_json_schema(args[0]))

    if origin is dict:
        assert len(args) == 2
        assert args[0] is str
        return type_dict(
            "object", desc, additionalProperties=type_to_json_schema(args[1])
        )

    if is_typeddict(t):
        annotations = get_type_hints(t, include_extras=True)
        return type_dict(
            "object",
            desc,
            properties={k: type_to_json_schema(v) for k, v in annotations.items()},
        )

    if t is dict:
        return type_dict("object", desc)
    if t is list:
        return type_dict("array", desc)
    if t is str:
        return type_dict("string", desc)
    if t is int:
        return type_dict("integer", desc)
    if t is float:
        return type_dict("number", desc)
    if t is bool:
        return type_dict("boolean", desc)
    if t is NoneType:
        return type_dict("null", desc)
    raise ValueError(f"Unsupported type: {t}")


def type_dict(type: str, description: str | None, **kwargs: JSONifiable) -> dict:
    return {
        "type": type,
        **({} if description is None else {"description": description}),
        **kwargs,
    }


class User(TypedDict):
    name: str
    age: int
    email: str
    is_active: bool
    blah: None


def _test():
    assert type_to_json_schema(User) == {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
            "email": {"type": "string"},
            "is_active": {"type": "boolean"},
            "blah": {"type": "null"},
        },
    }

    assert type_to_json_schema(dict) == {"type": "object"}

    def foo(
        a: int, b: str = "blah", *args, c: Annotated[str, "The c string"], **kwargs
    ) -> None:
        "Docstring for the function"
        pass

    assert func_to_schema(foo) == {
        "type": "function",
        "function": {
            "name": "foo",
            "description": "Docstring for the function",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "string"},
                    "c": {"type": "string", "description": "The c string"},
                },
                "required": ["a", "c"],
            },
        },
    }


# _test()
