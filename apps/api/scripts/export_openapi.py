import json
from pathlib import Path

from app.main import app


def export_openapi() -> None:
    schema = app.openapi()
    output_dir = Path(__file__).resolve().parent.parent / "generated"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "openapi.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"Exported OpenAPI spec to {output_file}")


if __name__ == "__main__":
    export_openapi()
