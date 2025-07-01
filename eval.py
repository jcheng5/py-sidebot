from pathlib import Path
from typing import Literal, TypeVar

import duckdb
import pandas as pd
from inspect_ai import Task, task
from inspect_ai.dataset import csv_dataset
from inspect_ai.scorer import Score, Target, accuracy, model_graded_fact, scorer
from inspect_ai.solver import (
    TaskState,
    chain,
    generate,
    solver,
    system_message,
    use_tools,
)
from inspect_ai.tool import tool
from inspect_ai.util import StoreModel, store_as
from pydantic import Field

from query import system_prompt
from shared import tips

T = TypeVar("T")

pd.read_csv("tips.csv")

sys_prompt = system_prompt(tips, "tips")


class UpdateDashboardCall(StoreModel):
    """A class to store calls to the `update_dashboard` tool."""

    calls: list[tuple[str, str]] = Field(default_factory=list)


@tool
def update_dashboard():
    async def execute(query: str, title: str):
        """Modifies the data presented in the data dashboard, based on the given SQL query, and also updates the title.

        Args:
            query: A DuckDB SQL query; must be a SELECT statement, or an empty string to reset the dashboard.
            title: A title to display at the top of the data dashboard, summarizing the intent of the SQL query.
        """
        sm = store_as(UpdateDashboardCall)
        sm.calls.append((query, title))

        if query != "":
            duckdb.query(query).to_df()

        return None

    return execute


@tool
def query_db():
    async def execute(query: str):
        """Perform a SQL query on the data, and return the results as JSON.

        Args:
            query: A DuckDB SQL query; must be a SELECT statement.
        """
        return duckdb.query(query).to_df().to_json(orient="records")

    return execute


@solver
def sidebot_solver():
    return chain(
        system_message(sys_prompt),
        use_tools(update_dashboard(), query_db()),
        generate(),
    )


@scorer(metrics=[accuracy()])
def sql_scorer():
    async def score(state: TaskState, target: Target):
        """Scores the task based on the most recent SQL query passed to the `update_dashboard` tool.
        If the query returns the same results as the target, it is scored as correct."""

        udc = store_as(UpdateDashboardCall)
        last_query = udc.calls[-1][0] if udc.calls else None

        if (last_query is None) != (target.text is None):
            if last_query is None:
                return Score(value="I", answer=last_query)
            else:
                return Score(value="I", answer=last_query)

        if last_query is None:
            return Score(value="C", answer=last_query)

        results = duckdb.query(last_query).to_df()
        expected_results = duckdb.query(target.text).to_df()

        value, explanation = compare_data_frames(results, expected_results)

        return Score(
            value=value,
            answer=last_query,
            explanation=explanation,
            metadata={
                "expected": expected_results.to_json(orient="records"),
                "actual": results.to_json(orient="records"),
            },
        )

    return score


def compare_data_frames(
    df1: pd.DataFrame, df2: pd.DataFrame
) -> tuple[Literal["C", "I", "P"], str]:
    """Compares two DataFrames and returns a score and explanation.

    Args:
        df1: The first DataFrame (actual results).
        df2: The second DataFrame (expected results).

    Returns:
        A tuple containing a score ("C" for correct, "I" for incorrect, "P" for partial)
        and an explanation string.
    """

    cols1 = set(df1.columns)
    cols2 = set(df2.columns)

    if cols2 - cols1:
        return ("I", "Query did not return all expected columns")

    caveats = []

    if cols1 - cols2:
        caveats.append("Query returned extra columns.")
        df1 = df1.drop(columns=cols1 - cols2)

    if not df1.equals(df2):
        if df1.sort_values(by=list(df1.columns)).equals(
            df2.sort_values(by=list(df2.columns))
        ):
            caveats.append("Query results differ by row order.")
        else:
            return ("I", "Query returned different values than expected")

    if caveats:
        return ("P", " ".join(caveats))
    else:
        return ("C", "Query returned expected results")


@task
def update_dashboard_sql():
    return Task(
        dataset=csv_dataset("eval-datasets/update_dashboard.csv"),
        solver=sidebot_solver(),
        scorer=sql_scorer(),
    )

@task
def query_db_answer():
    return Task(
        dataset=csv_dataset("eval-datasets/query_db.csv"),
        solver=sidebot_solver(),
        scorer=model_graded_fact(model="openai/gpt-4.1-mini"),
    )