"""Run with `python -m mcp_server --data-dir /path` from an MCP host."""

import argparse
from pathlib import Path

from mcp_server.server import build_server


def main() -> None:
    parser = argparse.ArgumentParser(description="VisionApp MCP stdio server")
    parser.add_argument("--data-dir", type=Path, required=True)
    arguments = parser.parse_args()
    build_server(arguments.data_dir).run(transport="stdio")


if __name__ == "__main__":
    main()
