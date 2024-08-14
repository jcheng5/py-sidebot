# Sidebot (Python Edition)

This is a demonstration of using an LLM to enhance a data dashboard written in [Shiny](https://shiny.posit.co/py/).

To run locally, you'll need to create an `.env` file in the repo root with `OPENAI_API_KEY=` followed by a valid OpenAI API key, and/or `ANTHROPIC_API_KEY=` if you want to use Claude. Or if those environment values are set some other way, you can skip the .env file.

Then run:

```bash
pip install -r requirements.txt
shiny run --launch-browser
```

## Warnings and limitations

This app sends at least your data schema to a remote LLM. As written, it also permits the LLM to run SQL queries against your data and get the results back. Please keep these facts in mind when dealing with sensitive data.

## Other versions

You can find the R version of this app at [https://github.com/jcheng5/r-sidebot](https://github.com/jcheng5/r-sidebot).