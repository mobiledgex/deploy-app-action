#!/usr/local/bin/python

import argparse
import os

def main(args):
    print(f"::set-output name=version::{os.getenv('GITHUB_REF')}")
    print(f"::set-output name=setup::{args.setup}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup", "-s", help="Setup to deploy app to",
                        default="stage")
    args = parser.parse_args()

    main(args)
