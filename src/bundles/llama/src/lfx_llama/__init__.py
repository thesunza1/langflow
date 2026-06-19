"""lfx-llama: Llama Vision component bundle."""
# Lazy import: the component class is only loaded when explicitly accessed.
# This avoids cascading into lfx extension discovery at startup.

def __getattr__(name):
    if name == "LlamaVisionComponent":
        from lfx_llama.components.llama.llama_vision import LlamaVisionComponent
        return LlamaVisionComponent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["LlamaVisionComponent"]
