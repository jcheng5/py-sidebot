import traceback
from pathlib import Path
from typing import Annotated

import dotenv
import duckdb
import faicons as fa
import plotly.express as px
from chatlas import ChatAnthropic, ChatOpenAI
from shiny import App, reactive, render, ui
from shinywidgets import output_widget, render_plotly

dotenv.load_dotenv()

import query
from explain_plot import explain_plot
from shared import tips  # Load data and compute static values

here = Path(__file__).parent

greeting = """
You can use this sidebar to filter and sort the data based on the columns available in the `tips` table. Here are some examples of the kinds of questions you can ask me:

1. Filtering: <span class="suggestion">Show only Male smokers who had Dinner on Saturday.</span>
2. Sorting: <span class="suggestion">Show all data sorted by total_bill in descending order.</span>
3. Answer questions about the data: <span class="suggestion">How do tip sizes compare between lunch and dinner?</span>

You can also say <span class="suggestion">Reset</span> to clear the current filter/sort, or <span class="suggestion">Help</span> for more usage tips.
"""

# Set to True to greatly enlarge chat UI (for presenting to a larger audience)
DEMO_MODE = False

icon_ellipsis = fa.icon_svg("ellipsis")
icon_explain = ui.img(src="stars.svg")

app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.chat_ui(
            "chat", height="100%", style=None if not DEMO_MODE else "zoom: 1.6;"
        ),
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
        min_height="600px",
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
        await explain_plot(fork_session(), scatterplot.widget)

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
        await explain_plot(fork_session(), tip_perc.widget)

    #
    # ✨ Sidebot ✨ -------------------------------------------------------------
    #

    Chat = ChatAnthropic
    chat_model = "claude-3-7-sonnet-latest"
    # Chat = ChatOpenAI
    # chat_model = "o1"
    chat_session = Chat(
        system_prompt=query.system_prompt(tips, "tips"), model=chat_model
    )
    print(chat_session.system_prompt)

    def fork_session():
        """
        Fork the current chat session into a new one. This is useful to create a new
        chat session that is a copy of the current one. The new session has the same
        system prompt and model as the current one, and it has all the turns of the
        current session. The main reason to do this is to continue the conversation
        on a branch, without affecting the existing session.
        TODO: chatlas Chat objects really should have a copy() method

        Returns:
            A new Chat object which is a fork of the current session.
        """
        new_session = Chat(system_prompt=chat_session.system_prompt, model=chat_model)
        new_session.register_tool(update_dashboard)
        new_session.register_tool(query_db)
        new_session.set_turns(chat_session.get_turns())
        return new_session

    chat = ui.Chat("chat", messages=[greeting])

    @chat.on_user_submit
    async def perform_chat(user_input: str):
        try:
            stream = await chat_session.stream_async(user_input, echo="all")
        except Exception as e:
            traceback.print_exc()
            return await chat.append_message(f"**Error**: {e}")

        await chat.append_message_stream(stream)

    async def update_filter(query, title):
        # Need this reactive lock/flush because we're going to call this from a
        # background asyncio task
        async with reactive.lock():
            current_query.set(query)
            current_title.set(title)
            await reactive.flush()

    async def update_dashboard(
        query: str,
        title: str,
    ):
        """Modifies the data presented in the data dashboard, based on the given SQL query, and also updates the title.

        Args:
          query: A DuckDB SQL query; must be a SELECT statement, or an empty string to reset the dashboard.
          title: A title to display at the top of the data dashboard, summarizing the intent of the SQL query.
        """

        # Verify that the query is OK; throws if not
        if query != "":
            await query_db(query)

        await update_filter(query, title)

    async def query_db(query: str):
        """Perform a SQL query on the data, and return the results as JSON.

        Args:
          query: A DuckDB SQL query; must be a SELECT statement.
        """
        return duckdb.query(query).to_df().to_json(orient="records")

    chat_session.register_tool(update_dashboard)
    chat_session.register_tool(query_db)


app = App(app_ui, server, static_assets=here / "www")
