"""Generate bilingual, auditable hull-line DXF drawings from classified offsets."""
import argparse
import json
from pathlib import Path
import sys

# Preserve importable legacy helpers used by previous project scripts.
from hull_core import *  # noqa: F403
from hull_data import load_bundle
from hull_drafting import produce


def generate(csv_path, config_path, out, skeleton=False, preview=False,
             profile_csv=None, deck_csv=None, transom_json=None, corrections_json=None):
    bundle = load_bundle(csv_path, config_path, profile_csv, deck_csv,
                         transom_json, corrections_json, skeleton=skeleton)
    return produce(bundle, Path(csv_path), Path(config_path), Path(out), skeleton,
                   preview, {"profile_source.csv": profile_csv,
                             "deck_source.csv": deck_csv,
                             "transom_source.json": transom_json,
                             "corrections_source.json": corrections_json})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("csv", "config", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--skeleton3d", action="store_true")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--profile-csv", type=Path)
    parser.add_argument("--deck-csv", type=Path)
    parser.add_argument("--transom-json", type=Path)
    parser.add_argument("--corrections", type=Path)
    args = parser.parse_args()
    try:
        report = generate(args.csv, args.config, args.out, args.skeleton3d,
                          args.preview, args.profile_csv, args.deck_csv,
                          args.transom_json, args.corrections)
    except (ValueError, KeyError, AssertionError) as error:
        print(f"Hull generation stopped: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
