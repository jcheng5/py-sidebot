import traceback
from pathlib import Path
from typing import Annotated

import duckdb
import faicons as fa
import plotly.express as px
from shiny import App, reactive, render, ui
from shinywidgets import output_widget, render_plotly

import query
from explain_plot import explain_plot
from shared import tips  # Load data and compute static values
from tool import Toolbox, tool

here = Path(__file__).parent

greeting = """
You can use this sidebar to filter and sort the data based on the columns available in the `tips` table. Here are some examples of the kinds of questions you can ask me:

1. Filtering: "Show only Male smokers who had Dinner on Saturday."
2. Sorting: "Show all data sorted by total_bill in descending order."
3. Answer questions about the data: "How do tip sizes compare between lunch and dinner?"

You can also say "Reset" to clear the current filter/sort, or "Help" for more usage tips.
"""

# Set to True to greatly enlarge chat UI (for presenting to a larger audience)
DEMO_MODE=False

icon_ellipsis = fa.icon_svg("ellipsis")
icon_explain = ui.img(src="stars.svg")

app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.input_select(
            "model",
            None,
            choices={
                "gpt-4o": "GPT-4o",
                "claude-3-5-sonnet-20240620": "Claude 3.5 Sonnet",
            },
        ).add_class("mb-3"),
        ui.chat_ui("chat", height="100%", style = None if not DEMO_MODE else "zoom: 1.6;"),
        open="desktop",
        width=400 if not DEMO_MODE else "50%",
        style="height: 100%;",
        gap="3px",
    ),
    ui.tags.link(rel="stylesheet", href="styles.css"),
    #
    # 🏷️ Header
    #
    ui.output_text("show_title", container=ui.h3),
    ui.output_code("show_query", placeholder=False).add_style(
        "max-height: 100px; overflow: auto;"
    ),
    #
    # 🎯 Value boxes
    #
    ui.layout_columns(
        ui.value_box(
            "Total tippers",
            ui.output_text("total_tippers"),
            showcase=fa.icon_svg("user", "regular"),
        ),
        ui.value_box(
            "Average tip", ui.output_text("average_tip"), showcase=fa.icon_svg("wallet")
        ),
        ui.value_box(
            "Average bill",
            ui.output_text("average_bill"),
            showcase=fa.icon_svg("dollar-sign"),
        ),
        fill=False,
    ),
    ui.layout_columns(
        #
        # 🔍 Data table
        #
        ui.card(
            ui.card_header("Tips data"),
            ui.output_data_frame("table"),
            full_screen=True,
        ),
        #
        # 📊 Scatter plot
        #
        ui.card(
            ui.card_header(
                "Total bill vs. tip",
                ui.span(
                    ui.input_action_link(
                        "interpret_scatter",
                        icon_explain,
                        class_="me-3",
                        style="color: inherit;",
                        aria_label="Explain scatter plot",
                    ),
                    ui.popover(
                        icon_ellipsis,
                        ui.input_radio_buttons(
                            "scatter_color",
                            None,
                            ["none", "sex", "smoker", "day", "time"],
                            inline=True,
                        ),
                        title="Add a color variable",
                        placement="top",
                    ),
                ),
                class_="d-flex justify-content-between align-items-center",
            ),
            output_widget("scatterplot"),
            full_screen=True,
        ),
        #
        # 📊 Ridge plot
        #
        ui.card(
            ui.card_header(
                "Tip percentages",
                ui.span(
                    ui.input_action_link(
                        "interpret_ridge",
                        icon_explain,
                        class_="me-3",
                        style="color: inherit;",
                        aria_label="Explain ridgeplot",
                    ),
                    ui.popover(
                        icon_ellipsis,
                        ui.input_radio_buttons(
                            "tip_perc_y",
                            None,
                            ["sex", "smoker", "day", "time"],
                            selected="day",
                            inline=True,
                        ),
                        title="Split by",
                    ),
                ),
                class_="d-flex justify-content-between align-items-center",
            ),
            output_widget("tip_perc"),
            full_screen=True,
        ),
        col_widths=[6, 6, 12],
    ),
    title="Restaurant tipping",
    fillable=True,
)


def server(input, output, session):

    #
    # 🔄 Reactive state/computation --------------------------------------------
    #

    current_query = reactive.Value("")
    current_title = reactive.Value("")
    messages = [query.system_prompt(tips, "tips")]

    @reactive.calc
    def tips_data():
        if current_query() == "":
            return tips
        return duckdb.query(current_query()).df()

    #
    # 🏷️ Header outputs --------------------------------------------------------
    #

    @render.text
    def show_title():
        return current_title()

    @render.text
    def show_query():
        return current_query()

    #
    # 🎯 Value box outputs -----------------------------------------------------
    #

    @render.text
    def total_tippers():
        return str(tips_data().shape[0])

    @render.text
    def average_tip():
        d = tips_data()
        if d.shape[0] > 0:
            perc = d.tip / d.total_bill
            return f"{perc.mean():.1%}"

    @render.text
    def average_bill():
        d = tips_data()
        if d.shape[0] > 0:
            bill = d.total_bill.mean()
            return f"${bill:.2f}"

    #
    # 🔍 Data table ------------------------------------------------------------
    #

    @render.data_frame
    def table():
        return render.DataGrid(tips_data())

    #
    # 📊 Scatter plot ----------------------------------------------------------
    #

    @render_plotly
    def scatterplot():
        color = input.scatter_color()
        return px.scatter(
            tips_data(),
            x="total_bill",
            y="tip",
            color=None if color == "none" else color,
            trendline="lowess",
        )

    @reactive.effect
    @reactive.event(input.interpret_scatter)
    async def interpret_scatter():
        await explain_plot(
            input.model(), [*messages], scatterplot.widget, toolbox=toolbox
        )

    #
    # 📊 Ridge plot ------------------------------------------------------------
    #

    @render_plotly
    def tip_perc():
        from ridgeplot import ridgeplot

        dat = tips_data()
        yvar = input.tip_perc_y()
        uvals = dat[yvar].unique()

        samples = [[dat.percent[dat[yvar] == val]] for val in uvals]

        plt = ridgeplot(
            samples=samples,
            labels=uvals,
            bandwidth=0.01,
            colorscale="viridis",
            # Prevent a divide-by-zero error that row-index is susceptible to
            colormode="row-index" if len(uvals) > 1 else "mean-minmax",
        )

        plt.update_layout(
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5
            )
        )

        return plt

    @reactive.effect
    @reactive.event(input.interpret_ridge)
    async def interpret_ridge():
        await explain_plot([*messages], tip_perc.widget, query_db)

    #
    # ✨ Sidebot ✨ -------------------------------------------------------------
    #

    chat = ui.Chat(
        "chat",
        messages=[{"role": "assistant", "content": greeting}],
        tokenizer=None,
    )

    @chat.on_user_submit
    async def perform_chat():
        with reactive.isolate():
            chat_task(input.model(), messages, chat.user_input())

    @reactive.extended_task
    async def chat_task(model, messages, user_input):
        try:
            stream = query.perform_query(
                messages, user_input, model=model, toolbox=toolbox
            )
            return stream
        except Exception as e:
            traceback.print_exc()
            return f"**Error**: {e}", None, None

    @reactive.effect
    async def on_chat_complete():
        stream = chat_task.result()
        await chat.append_message_stream(stream)

    async def update_filter(query, title):
        # Need this reactive lock/flush because we're going to call this from a
        # background asyncio task
        async with reactive.lock():
            current_query.set(query)
            current_title.set(title)
            await reactive.flush()

    @tool
    async def update_dashboard(
        query: Annotated[str, "A DuckDB SQL query; must be a SELECT statement, or \"\"."],
        title: Annotated[
            str,
            "A title to display at the top of the data dashboard, summarizing the intent of the SQL query.",
        ],
    ):
        """Modifies the data presented in the data dashboard, based on the given SQL query, and also updates the title."""

        # Verify that the query is OK; throws if not
        if query != "":
            await query_db(query)

        await update_filter(query, title)

    @tool(name="query")
    async def query_db(
        query: Annotated[str, "A DuckDB SQL query; must be a SELECT statement."]
    ):
        """Perform a SQL query on the data, and return the results as JSON."""
        return duckdb.query(query).to_df().to_json(orient="records")

    toolbox = Toolbox(update_dashboard, query_db)


app = App(app_ui, server, static_assets=here / "www")
