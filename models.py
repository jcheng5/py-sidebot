import importlib

import dotenv

dotenv.load_dotenv()


available_models = {
    "gpt-4o-mini": ("langchain_openai", "ChatOpenAI", {}),
    "gpt-4o": ("langchain_openai", "ChatOpenAI", {}),
    "claude-3-5-sonnet-20240620": ("langchain_anthropic", "ChatAnthropic", {}),
    "Llama3-8b-8192": ("langchain_groq", "ChatGroq", {}),
    "Llama-3.1-8b-Instant": ("langchain_groq", "ChatGroq", {}),
    "Llama-3.1-70b-Versatile": ("langchain_groq", "ChatGroq", {}),
}

def get_model(model_name: str):
    module_name, clazz, kwargs = available_models[model_name]
    module = importlib.import_module(module_name)
    return getattr(module, clazz)(model=model_name, **kwargs)



# from langchain_community.chat_models.llamacpp import ChatLlamaCpp
# llm = ChatLlamaCpp(
#     model_path="Llama-3-Groq-8B-Tool-Use-Q5_K_M.gguf",
#     max_tokens=1024 * 16,
#     n_ctx=1024 * 16,
# )
