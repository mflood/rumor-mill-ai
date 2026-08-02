"""Verify a deployed Rumor Mill web dyno and its static assets."""

import argparse

from rumor_mill.deployment import smoke


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "base_url", help="Deployed app origin, such as https://example.herokuapp.com"
    )
    args = parser.parse_args()
    smoke(args.base_url)
    print("Deployment smoke check passed.")


if __name__ == "__main__":
    main()
