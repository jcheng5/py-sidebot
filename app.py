import duckdb
import faicons as fa
import plotly.express as px
from shiny import reactive, render, req
from shiny.express import input, ui
from shinywidgets import render_plotly

import query
from explain_plot import explain_plot

# Load data and compute static values
from shared import app_dir, tips

greeting = """
You can use this sidebar to filter and sort the data based on the columns available in the `tips` table. Here are some examples of the kinds of questions you can ask me:

1. Filtering: "Show only Male smokers who had Dinner on Saturday."
2. Sorting: "Show all data sorted by total_bill in descending order."
3. Answer questions about the data: "How do tip sizes compare between lunch and dinner?"

You can also say "Reset" to clear the current filter/sort, or "Help" for more usage tips.
"""

# Add page title and sidebar
ui.page_opts(title="Restaurant tipping", fillable=True)

current_query = reactive.Value("")
current_title = reactive.Value(None)

with ui.sidebar(open="desktop", width=400, style="height: 100%;", gap="3px"):
    chat = ui.Chat(
        "chat",
        messages=[
            query.system_prompt(tips, "tips"),
            {"role": "assistant", "content": greeting},
        ],
        tokenizer=None,
    )
    chat.ui(height="100%")

    @chat.on_user_submit
    async def perform_chat():
        with ui.Progress() as p:
            response, sql, title = await query.perform_query(
                chat.messages(), query_db, lambda msg: p.set(message=msg)
            )
        await chat.append_message({"role": "assistant", "content": response})
        if sql is not None:
            current_query.set(sql)
        if title is not None:
            current_title.set(title)


# Add main content
ICONS = {
    "user": fa.icon_svg("user", "regular"),
    "wallet": fa.icon_svg("wallet"),
    "currency-dollar": fa.icon_svg("dollar-sign"),
    "ellipsis": fa.icon_svg("ellipsis"),
}


@render.express(container=ui.h3)
def show_title():
    current_title()


@render.express(container=ui.pre)
def show_query():
    current_query()


with ui.layout_columns(fill=False):
    with ui.value_box(showcase=ICONS["user"]):
        "Total tippers"

        @render.express
        def total_tippers():
            tips_data().shape[0]

    with ui.value_box(showcase=ICONS["wallet"]):
        "Average tip"

        @render.express
        def average_tip():
            d = tips_data()
            if d.shape[0] > 0:
                perc = d.tip / d.total_bill
                f"{perc.mean():.1%}"

    with ui.value_box(showcase=ICONS["currency-dollar"]):
        "Average bill"

        @render.express
        def average_bill():
            d = tips_data()
            if d.shape[0] > 0:
                bill = d.total_bill.mean()
                f"${bill:.2f}"


with ui.layout_columns(col_widths=[6, 6, 12]):
    with ui.card(full_screen=True):
        ui.card_header("Tips data")

        @render.data_frame
        def table():
            return render.DataGrid(tips_data())

    with ui.card(full_screen=True):
        with ui.card_header(class_="d-flex justify-content-between align-items-center"):
            "Total bill vs tip"
            with ui.span():
                ui.input_action_link(
                    "interpret_scatter", fa.icon_svg("robot"), class_="me-3"
                )
                with ui.popover(title="Add a color variable", placement="top"):
                    ICONS["ellipsis"]
                    ui.input_radio_buttons(
                        "scatter_color",
                        None,
                        ["none", "sex", "smoker", "day", "time"],
                        inline=True,
                    )

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
            await explain_plot(chat.messages(), scatterplot.widget, query_db)

    with ui.card(full_screen=True):
        with ui.card_header(class_="d-flex justify-content-between align-items-center"):
            "Tip percentages"
            with ui.span():
                ui.input_action_link(
                    "interpret_ridge", fa.icon_svg("robot"), class_="me-3"
                )
                with ui.popover(title="Add a color variable"):
                    ICONS["ellipsis"]
                    ui.input_radio_buttons(
                        "tip_perc_y",
                        "Split by:",
                        ["sex", "smoker", "day", "time"],
                        selected="day",
                        inline=True,
                    )

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
            await explain_plot(chat.messages(), tip_perc.widget, query_db)


ui.include_css(app_dir / "styles.css")

# --------------------------------------------------------
# Reactive calculations and effects
# --------------------------------------------------------


@reactive.calc
def tips_data():
    if current_query() == "":
        return tips
    return duckdb.query(current_query()).df()


def query_db(query: str):
    return duckdb.query(query).to_df().to_json(orient="records")
