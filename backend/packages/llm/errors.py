class LLMError(RuntimeError):
    pass


class LLMExecutionLimitError(LLMError):
    """The run cannot admit another paid request within its execution budget."""
