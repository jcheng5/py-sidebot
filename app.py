import os
import traceback
from pathlib import Path

import dotenv
import duckdb
import faicons as fa
import numpy as np
import plotly.express as px
import plotly.figure_factory as ff
from chatlas import ChatAnthropic
from shiny import App, reactive, render, ui
from shinywidgets import output_widget, render_plotly

from explain_plot import explain_plot
from shared import birds, birds_system_prompt  # Load data and compute static values

# Create a list of unique bird name/scientific name pairs for the model to see
species_csv = (
    birds[["bird_name", "scientific_name"]].drop_duplicates().to_csv(index=False)
)

dotenv.load_dotenv()
here = Path(__file__).parent

greeting = """Hello! I can help you explore and analyze your bird sightings data. I can filter, sort, calculate statistics, and answer questions about birds, locations, or observation methods. For transparency, I'll always show you the SQL used.

Suggestions:

* <span class="suggestion submit">Show only American Robins</span>
* <span class="suggestion submit">Limit to sightings between 6AM-10AM</span>
* <span class="suggestion submit">Filter to observations where the count was high (90+ percentile)</span>

You can also say <span class="suggestion submit">Reset</span> to clear the current filter/sort, or <span class="suggestion submit">Help</span> for more usage tips.

<small class="text-muted">Data source: [eBird](https://science.ebird.org/en/use-ebird-data)</small>
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
            "Total sightings",
            ui.output_text("total_sightings"),
            showcase=fa.icon_svg("binoculars"),
        ),
        ui.value_box(
            "Total birds sighted",
            ui.output_text("total_birds"),
            showcase=fa.icon_svg("crow"),
        ),
        ui.value_box(
            "Most common bird",
            ui.output_text("most_common"),
            showcase=fa.icon_svg("trophy"),
        ),
        fill=False,
    ),
    ui.layout_columns(
        #
        # 🔍 Data table
        #
        ui.card(
            ui.card_header("Raw data"),
            ui.output_data_frame("table"),
            full_screen=True,
        ),
        #
        # 📊 Scatter plot
        #
        ui.card(
            ui.card_header(
                "Count by bird",
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
                        ui.input_slider(
                            "top_n_birds",
                            "Number of species to show",
                            min=5,
                            max=25,
                            value=10,
                            step=1,
                        ),
                        ui.input_radio_buttons(
                            "sort_direction",
                            "Sort by",
                            ["most", "least"],
                            selected="most",
                            inline=True,
                        ),
                        title="Display options",
                        placement="top",
                    ),
                ),
                class_="d-flex justify-content-between align-items-center",
            ),
            output_widget("barplot"),
            full_screen=True,
        ),
        #
        # 📊 Location map
        #
        ui.card(
            ui.card_header(
                "Bird sighting locations",
                ui.span(
                    ui.input_action_link(
                        "interpret_map",
                        icon_explain,
                        class_="me-3",
                        style="color: inherit;",
                        aria_label="Explain map",
                    ),
                    ui.popover(
                        icon_ellipsis,
                        ui.input_slider(
                            "map_detail",
                            "Detail level",
                            min=5,
                            max=100,
                            value=30,
                        ),
                        ui.input_radio_buttons(
                            "map_style",
                            "Map style",
                            {
                                "light": "Minimal",
                                "streets": "Streets",
                                "satellite-streets": "Satellite",
                            },
                            selected="light",
                        ),
                        ui.input_radio_buttons(
                            "map_metric",
                            "Show on map",
                            {
                                "sightings": "Number of observations",
                                "birds": "Birds sighted",
                            },
                            selected="birds",
                        ),
                        title="Map options",
                    ),
                ),
                class_="d-flex justify-content-between align-items-center",
            ),
            output_widget("location_map"),
            full_screen=True,
        ),
        col_widths=[6, 6, 12],
        min_height="600px",
    ),
    title="Tuscaloosa Bird Sightings",
    fillable=True,
)


def server(input, output, session):
    #
    # 🔄 Reactive state/computation --------------------------------------------
    #

    current_query = reactive.Value("")
    current_title = reactive.Value("")

    @reactive.calc
    def birds_data():
        if current_query() == "":
            return birds
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
    def total_sightings():
        return str(birds_data().shape[0])

    @render.text
    def total_birds():
        d = birds_data()

        if d.shape[0] > 0:
            return str(int(d["count"].sum()))
        else:
            return "0"

    @render.text
    def most_common():
        d = birds_data()
        if d.shape[0] > 0:
            most_common_species = d.groupby("bird_name")["count"].sum().idxmax()
            return most_common_species

    #
    # 🔍 Data table ------------------------------------------------------------
    #

    @render.data_frame
    def table():
        return render.DataGrid(birds_data())

    #
    # 📊 Histogram --------------------------------------------------------------
    #

    @render_plotly
    def barplot():
        d = birds_data()

        # Group by bird_name and sum the counts
        bird_counts = d.groupby("bird_name")["count"].sum().reset_index()

        # Sort by count based on user selection
        ascending = input.sort_direction() == "least"
        bird_counts = bird_counts.sort_values(by="count", ascending=ascending).head(
            input.top_n_birds()
        )

        return px.bar(
            bird_counts,
            x="bird_name",
            y="count",
            labels={
                "bird_name": "Bird Name",
                "count": "Total Count",
            },
        )

    @reactive.effect
    @reactive.event(input.interpret_scatter)
    async def interpret_scatter():
        await explain_plot(fork_session(), barplot.widget)

    #
    # 🗺️ Location map ----------------------------------------------------------
    #

    @render_plotly
    def location_map():
        px.set_mapbox_access_token(os.getenv("MAPBOX_TOKEN"))
        df = birds_data()

        zoom = None
        center = None
        with reactive.isolate():
            try:

                def preserve_view(mapbox):
                    nonlocal zoom, center
                    zoom = mapbox.zoom
                    center = mapbox.center

                location_map.widget.for_each_mapbox(preserve_view)
            except Exception:
                # This is expected to fail the first time the map is rendered
                pass

        # Choose aggregation function and color column based on user selection
        if input.map_metric() == "sightings":
            color_col = None  # Each row represents one sighting
            agg_func = len  # Count the number of rows
            color_label = "Number of observations"
        else:
            color_col = "count"  # Use the count column
            agg_func = np.sum  # Sum the counts
            color_label = "Birds sighted"

        fig = ff.create_hexbin_mapbox(
            data_frame=df,
            lat="latitude",
            lon="longitude",
            mapbox_style=input.map_style(),
            nx_hexagon=input.map_detail(),
            zoom=zoom,
            center=center,
            opacity=0.7,
            min_count=1,
            labels={"color": color_label},
            color=color_col,
            agg_func=agg_func,
            color_continuous_scale="Inferno",
        )
        fig._config = fig._config | {"scrollZoom": True}

        return fig

    @reactive.effect
    @reactive.event(input.interpret_map)
    async def interpret_map():
        await explain_plot(fork_session(), location_map.widget)

    #
    # ✨ Sidebot ✨ -------------------------------------------------------------
    #

    Chat = ChatAnthropic
    chat_model = "claude-3-7-sonnet-latest"
    # Chat = ChatOpenAI
    # chat_model = "gpt-4.1"
    # from chatlas import ChatGoogle

    # Chat = ChatGoogle
    # chat_model = "gemini-2.5-pro"
    # from chatlas import ChatOllama
    # Chat = ChatOllama
    # chat_model = "mistral-small:24b"
    # import os
    # def Chat(*args, **kwargs):
    #     return ChatOpenAI(
    #         *args,
    #         **kwargs,
    #         base_url="https://openrouter.ai/api/v1",
    #         api_key=os.getenv("OPENROUTER_API_KEY"),
    #     )
    # chat_model = "deepseek/deepseek-chat-v3-0324"

    chat_session = Chat(
        system_prompt=birds_system_prompt,
        model=chat_model,
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
