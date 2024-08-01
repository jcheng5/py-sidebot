import base64
import tempfile
from typing import Callable, cast

import plotly.graph_objects as go
from shiny import ui

import query

INSTRUCTIONS = """
Interpret this plot, which is based on the current state of the data (i.e. with
filtering applied, if any). Try to make specific observations if you can, but
be conservative in drawing firm conclusions and express uncertainty if you
can't be confident.
""".strip()

counter = 0  # Never re-use the same chat ID


async def explain_plot(
    messages: list[dict],
    plot_widget: go.FigureWidget,
    query_db: Callable[[str], str],
    *,
    model: str = "claude-3-5-sonnet-20240620",
) -> None:
    # Make sure not to mutate whatever we were given
    messages = [*messages]

    try:
        with tempfile.TemporaryFile() as f:
            plot_widget.write_image(f)
            f.seek(0)
            img_b64 = base64.b64encode(f.read()).decode("utf-8")
            img_url = f"data:image/png;base64,{img_b64}"

        global counter
        counter += 1
        chat = ui.Chat(f"explain_plot_chat_{counter}")

        # TODO: Call chat.destroy() when the modal is dismissed?

        ui.modal_show(make_modal_dialog(img_url, chat.ui(height="100%")))

        async def ask(user_prompt):
            stream = query.perform_query(
                messages,
                user_prompt,
                query_db=query_db,
                model=model,
                update_filter=lambda *args: None,
            )

            await chat.append_message_stream(stream)

        # Ask the initial question
        await ask(
            [
                {"type": "text", "text": INSTRUCTIONS},
                {"type": "image_url", "image_url": {"url": img_url}},
            ]
        )

        # Allow followup questions
        @chat.on_user_submit
        async def on_user_submit():
            await ask(chat.user_input())

    except Exception as e:
        ui.notification_show(str(e), type="error")


def make_modal_dialog(img_url, chat_ui):
    return ui.modal(
        ui.tags.button(
            type="button",
            class_="btn-close d-block ms-auto mb-3",
            data_bs_dismiss="modal",
            aria_label="Close",
        ),
        ui.img(
            src=img_url,
            style="max-width: min(100%, 500px);",
            class_="d-block border mx-auto mb-3",
        ),
        ui.div(
            chat_ui,
            style="overflow-y: auto; max-height: min(60vh, 600px);",
        ),
        size="l",
        easy_close=True,
        title=None,
        footer=None,
    ).add_style("--bs-modal-margin: 1.75rem;")
