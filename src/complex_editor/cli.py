"""CLI entry points for Complex‑Editor."""
import argparse, sys
def main():
    parser = argparse.ArgumentParser(description="Complex‑Editor CLI")
    parser.add_argument("--version", action="version", version="0.0.1")
    args = parser.parse_args()
    print("Complex‑Editor CLI – nothing here yet")
if __name__ == "__main__":
    main()
