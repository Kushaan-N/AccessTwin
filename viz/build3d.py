"""Bundle the 3D walkthrough into one self-contained HTML file.

three.js ships as an ES module ending in a single `export{...}` list of
minified internal names. We rewrite that list into `const THREE = {...}`
and concatenate the app after it, which gives the app clean names
without needing a bundler, an import map, or any network request --
the page has to run under a strict CSP with no external hosts.

Run:  python3 viz/build3d.py
Then: open out/index.html
"""
from __future__ import annotations
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def three_as_global(src: str) -> str:
    """Turn the trailing ESM export list into a THREE namespace object."""
    i = src.rfind("export{")
    if i < 0:
        sys.exit("three.js: no export block found")
    j = src.index("}", i)
    body = src[i + len("export{"):j]

    pairs = []
    for item in body.split(","):
        item = item.strip()
        if not item:
            continue
        m = re.match(r"^(\S+)\s+as\s+(\S+)$", item)
        if m:
            pairs.append(f"{m.group(2)}:{m.group(1)}")
        else:
            pairs.append(f"{item}:{item}")
    ns = "const THREE={" + ",".join(pairs) + "};"
    return src[:i] + ns + src[j + 1:]


def main():
    three_path = os.path.join(ROOT, "vendor", "three.module.min.js")
    scene_path = os.path.join(ROOT, "out", "scene.json")
    for p in (three_path, scene_path):
        if not os.path.exists(p):
            sys.exit(f"missing {p}")

    three = three_as_global(open(three_path).read())
    detail = open(os.path.join(ROOT, "viz", "detail3d.js")).read()
    app = open(os.path.join(ROOT, "viz", "app3d.js")).read()
    shell = open(os.path.join(ROOT, "viz", "shell3d.html")).read()
    scene = json.load(open(scene_path))

    # </script> inside JSON would close the tag early.
    blob = json.dumps(scene, separators=(",", ":")).replace("</", "<\\/")

    body = (shell
            # Capture load-time and animation-loop errors onto window so a
            # failure is inspectable even when devtools is not attached.
            + '\n<script>window.__ERR=[];'
            + 'addEventListener("error",e=>window.__ERR.push('
            + '(e.message||"")+" @"+(e.filename||"")+":"+(e.lineno||0)));'
            + 'addEventListener("unhandledrejection",'
            + 'e=>window.__ERR.push("promise: "+e.reason));</script>'
            + '\n<script type="application/json" id="scene-data">'
            + blob + "</script>\n"
            + '<script type="module">\n'
            + "window.__SCENE__=JSON.parse("
            + "document.getElementById('scene-data').textContent);\n"
            # The app runs inside an IIFE. three.js is minified down to
            # single-letter top-level bindings (D, P, T ...) and the app
            # uses the same obvious names; sharing one module scope makes
            # them collide at parse time.
            + three + "\nwindow.THREE=THREE;\n"
            + "(function(){\n" + detail + "\n" + app + "\n})();\n</script>\n")

    os.makedirs(os.path.join(ROOT, "out"), exist_ok=True)
    art = os.path.join(ROOT, "out", "artifact3d.html")
    with open(art, "w") as fh:
        fh.write(body)

    doc = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
           '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
           '<title>Access-Twin — who can actually get through</title>\n'
           '<style>html,body{margin:0;padding:0}</style>\n</head>\n<body>\n'
           + body + "\n</body>\n</html>\n")
    idx = os.path.join(ROOT, "out", "index.html")
    with open(idx, "w") as fh:
        fh.write(doc)

    print(f"scene  {len(blob)/1024:8.0f} kB")
    print(f"three  {len(three)/1024:8.0f} kB")
    print(f"app    {(len(app)+len(detail))/1024:8.0f} kB")
    print(f"page   {len(doc)/1024:8.0f} kB -> {idx}")
    print(f"                    -> {art}  (body-only, for publishing)")


if __name__ == "__main__":
    main()
