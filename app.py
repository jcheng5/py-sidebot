import traceback
from pathlib import Path

import duckdb
import faicons as fa
import plotly.express as px
from shiny import App, reactive, render, ui
from shinywidgets import output_widget, render_plotly

import query
from explain_plot import explain_plot
from shared import tips  # Load data and compute static values

here = Path(__file__).parent

greeting = """
You can use this sidebar to filter and sort the data based on the columns available in the `tips` table. Here are some examples of the kinds of questions you can ask me:

1. Filtering: "Show only Male smokers who had Dinner on Saturday."
2. Sorting: "Show all data sorted by total_bill in descending order."
3. Answer questions about the data: "How do tip sizes compare between lunch and dinner?"

You can also say "Reset" to clear the current filter/sort, or "Help" for more usage tips.
"""

icon_ellipsis = fa.icon_svg("ellipsis")
icon_explain = ui.img(src="stars.svg")

app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.chat_ui("chat", height="100%"),
        open="desktop",
        width=400,
        style="height: 100%;",
        gap="3px",
    ),
    ui.tags.link(rel="stylesheet", href="styles.css"),
    #
    # 🏷️ Header
    #
    ui.output_text("show_title", container=ui.h3),
    ui.output_code("show_query", placeholder=False),
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
        await explain_plot(chat.messages(), scatterplot.widget, query_db)

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
        await explain_plot(chat.messages(), tip_perc.widget, query_db)

    #
    # ✨ Sidebot ✨ -------------------------------------------------------------
    #

    chat = ui.Chat(
        "chat",
        messages=[
            query.system_prompt(tips, "tips"),
            {"role": "assistant", "content": greeting},
        ],
        tokenizer=None,
    )

    @chat.on_user_submit
    async def perform_chat():
        chat_task(chat.messages())

    @reactive.extended_task
    async def chat_task(messages):
        try:
            response, sql, title = await query.perform_query(
                messages,
                query_db,
            )
            return response, sql, title
        except Exception as e:
            traceback.print_exc()
            return f"**Error**: {e}", None, None

    @reactive.effect
    async def on_chat_complete():
        response, sql, title = chat_task.result()
        await chat.append_message({"role": "assistant", "content": response})
        if sql is not None:
            current_query.set(sql)
        if title is not None:
            current_title.set(title)


def query_db(query: str):
    "Callback for when chat model wants to query the database"

    return duckdb.query(query).to_df().to_json(orient="records")


app = App(app_ui, server, static_assets=here / "www")
