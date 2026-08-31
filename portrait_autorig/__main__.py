from __future__ import annotations

import argparse

from .compiler import compile_bundle, compile_legacy_run


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile a portrait into a Rig Bundle")
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--legacy", action="store_true", help="read a pre-v1 flat run")
    parser.add_argument("--soften-back-hair", action="store_true")
    args = parser.parse_args()
    gradient = ("back hair",) if args.soften_back_hair else ()
    compile_fn = compile_legacy_run if args.legacy else compile_bundle
    print(compile_fn(args.input, args.output, gradient_tags=gradient))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

