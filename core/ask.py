"""Ask entry point: a grounded, cited answer from the indexed course.

Usage:
    python -m ask "What is a piecewise constant approximation?"
"""

import argparse

from core.answer import answer


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the course tutor a question.")
    parser.add_argument("question", help="The question to ask.")
    parser.add_argument("-k", type=int, default=5, help="Number of chunks to retrieve.")
    parser.add_argument(
        "--raw", action="store_true", help="Also print the raw LLM output (with [n] markers)."
    )
    args = parser.parse_args()

    result = answer(args.question, k=args.k)
    if args.raw:
        print("=== RAW LLM OUTPUT (before citation remapping) ===")
        print(result["raw"])
        print("=== FINAL ANSWER (after remapping) ===")
    print(result["answer"])
    if result["sources"]:
        print("\nSources:")
        for source in result["sources"]:
            print(f"  - {source}")


if __name__ == "__main__":
    main()
