#!/usr/bin/env python3
from src.core.server import UnifiedMCPServer


def main() -> None:
    server = UnifiedMCPServer()
    server.load()
    server.run()


if __name__ == "__main__":
    main()
