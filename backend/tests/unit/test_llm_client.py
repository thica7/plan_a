from packages.config import Settings
from packages.llm import DoubaoClient


def test_extract_json_accepts_trailing_text_after_first_object() -> None:
    client = DoubaoClient(
        Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        )
    )

    payload = client._extract_json('{"ok": true}\n{"extra": false}')

    assert payload == {"ok": True}
