from app.config import get_settings
from app.llm.base import LLMProvider
from app.llm.mock import MockLLMProvider


class ProviderNotConfigured(RuntimeError):
    pass


def get_llm_provider() -> LLMProvider:
    name = get_settings().llm_provider.lower()
    if name == "mock":
        return MockLLMProvider()
    # Real providers are added once the enterprise confirms which LLM service is approved
    # (e.g. Azure OpenAI, Amazon Bedrock, Anthropic API) and credentials are issued. They must
    # use app.llm.prompts and return the same CriterionResult structure.
    raise ProviderNotConfigured(
        f"LLM provider '{name}' is not implemented in this milestone. Set LLM_PROVIDER=mock."
    )
