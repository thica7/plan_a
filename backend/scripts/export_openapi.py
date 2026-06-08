import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402


def main() -> None:
    payload = json.dumps(app.openapi(), ensure_ascii=False, indent=2)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(payload + "\n", encoding="utf-8")
        return
    print(payload)


if __name__ == "__main__":
    main()
