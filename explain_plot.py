import base64
import tempfile
from typing import Callable, cast

import plotly.graph_objects as go
from shiny.express import expressify, ui

import query


async def explain_plot(
    messages: list[dict],
    plot_widget: go.FigureWidget,
    query_db: Callable[[str], str],
) -> None:
    try:
        with tempfile.TemporaryFile() as f:
            plot_widget.write_image(f)
            f.seek(0)
            img_url = (
                f"data:image/png;base64,{base64.b64encode(f.read()).decode('utf-8')}"
            )
        response, _, _ = await query.perform_query(
            [
                *messages,
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Interpret this plot, which is based on the current state of the data (i.e. with filtering applied, if any). Try to make specific observations if you can, but be conservative in drawing firm conclusions and express uncertainty if you can't be confident.",
                        },
                        {"type": "image_url", "image_url": {"url": img_url}},
                    ],
                },
            ],
            query_db,
        )

        @expressify
        def make_modal():
            with ui.hold() as result:
                ui.img(
                    src=img_url,
                    style="max-width: min(100%, 400px);",
                    class_="d-block border mx-auto mb-3",
                )
                with ui.div(style="max-height: 300px; overflow-y: auto;"):
                    ui.markdown(response)

            return ui.modal(*cast(list[ui.Tag], result), size="l")

        ui.modal_show(make_modal())
    except Exception as e:
        ui.notification_show(str(e), type="error")
