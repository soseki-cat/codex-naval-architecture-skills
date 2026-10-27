"""Add owned annotations to a new DXF while preserving the input document."""
import argparse
import json
from pathlib import Path
import sys

import ezdxf
from hull_annotations import annotate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--config", type=Path, help="Optional annotation configuration JSON")
    parser.add_argument("--language", choices=("zh", "en"), default="zh")
    args = parser.parse_args(argv)
    if args.input.resolve() == args.out.resolve() or (args.out.exists() and args.input.exists() and args.out.samefile(args.input)):
        parser.error("--out must differ from --input; source DXFs are preserved")
    try:
        config = json.loads(args.config.read_text(encoding="utf-8-sig")) if args.config else None
        doc = ezdxf.readfile(args.input)
        report = annotate(doc, args.language, config)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        doc.saveas(args.out)
        reread = ezdxf.readfile(args.out)
        audit = reread.audit()
        report["output"] = str(args.out.resolve())
        report["audit"] = {"errors": len(audit.errors), "fixes": len(audit.fixes)}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if audit.errors or audit.fixes or report["unplaced"] else 0
    except (OSError, ValueError, ezdxf.DXFError) as error:
        print("Annotation failed: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
