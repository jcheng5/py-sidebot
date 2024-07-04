import duckdb
import faicons as fa
import plotly.express as px
from shiny import App, reactive, render, req, ui
from shinywidgets import output_widget, render_plotly

import query

# Load data and compute static values
from shared import app_dir, tips

greeting = """
You can use this sidebar to filter and sort the data based on the columns available in the `tips` table. Here are some examples of the kinds of questions you can ask me:

1. Filter by specific values: 'Show only Female tippers on Sunday.'
2. Combine multiple filters: 'Show only Male smokers who had Dinner on Saturday.'
3. Sort the data: 'Show all data sorted by total_bill in descending order.'
4. Combine filters and sorting: 'Show Female tippers on Friday sorted by tip amount in ascending order.'

Please note that the query will always return all columns in the table, so requests that require a different set of columns will not be possible.
"""

ICONS = {
    "user": fa.icon_svg("user", "regular"),
    "wallet": fa.icon_svg("wallet"),
    "currency-dollar": fa.icon_svg("dollar-sign"),
    "ellipsis": fa.icon_svg("ellipsis"),
}

app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.chat_ui("chat", height="100%"),
        open="desktop",
        width=400,
        style="height: 100%;",
        gap="3px",
    ),
    ui.include_css(app_dir / "styles.css"),
    ui.layout_columns(
        ui.value_box(
            "Total tippers", ui.output_text("total_tippers"), showcase=ICONS["user"]
        ),
        ui.value_box(
            "Average tip", ui.output_text("average_tip"), showcase=ICONS["wallet"]
        ),
        ui.value_box(
            "Average bill",
            ui.output_text("average_bill"),
            showcase=ICONS["currency-dollar"],
        ),
        fill=False,
    ),
    ui.layout_columns(
        ui.card(
            ui.card_header("Tips data"),
            ui.output_data_frame("table"),
            full_screen=True,
        ),
        ui.card(
            ui.card_header(
                "Total bill vs tip",
                ui.popover(
                    ICONS["ellipsis"],
                    ui.input_radio_buttons(
                        "scatter_color",
                        None,
                        ["none", "sex", "smoker", "day", "time"],
                        inline=True,
                    ),
                    title="Add a color variable",
                    placement="top",
                ),
                class_="d-flex justify-content-between align-items-center",
            ),
            output_widget("scatterplot"),
            full_screen=True,
        ),
        ui.card(
            ui.card_header(
                "Tip percentages",
                ui.popover(
                    ICONS["ellipsis"],
                    ui.input_radio_buttons(
                        "tip_perc_y",
                        "Split by:",
                        ["sex", "smoker", "day", "time"],
                        selected="day",
                        inline=True,
                    ),
                    title="Add a color variable",
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
    # Reactive values that are under the "control" of the LLM
    current_query = reactive.Value("")
    current_title = reactive.Value(None)

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
        response, sql, title = await query.perform_query(chat.messages())
        await chat.append_message({"role": "assistant", "content": response})
        if sql is not None:
            current_query.set(sql)
        if title is not None:
            current_title.set(title)

    @reactive.calc
    def tips_data():
        if current_query() == "":
            return tips
        return duckdb.query(current_query()).df()

    @render.express
    def title():
        _ = req(current_title(), current_query())
        with ui.h3():
            current_title()
        with ui.pre():
            current_query()

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

    @render.data_frame
    def table():
        return render.DataGrid(tips_data())

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

    @render_plotly
    def tip_perc():
        from ridgeplot import ridgeplot

        dat = tips_data()
        dat["percent"] = dat.tip / dat.total_bill
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


app = App(app_ui, server)
