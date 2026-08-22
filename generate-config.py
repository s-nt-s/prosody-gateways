
from pathlib import Path
from os import environ
import re

root = Path(".")


def _sub(txt: str, **kwargs) -> str:
    for k, v in kwargs.items():
        txt = re.sub(k, v, txt)
    return txt.strip()


(root / "env.example.txt").write_text(
    _sub(
        (root / ".env").read_text(),
        **{
            r".*\b(ROSTER_FIX)\b.*": "",
            r"#.*": "",
            r'=[^"].*': '="*******"',
            r"XMPP_ADMIN_NAME=.*": r'XMPP_ADMIN_NAME="admin"',
        }
    )
)

def _g(key: str) -> str:
    v = environ[key]
    v = v.strip()
    if len(v) == 0:
        raise ValueError(f"Environment variable {key} is empty")
    return v

for template_path in root.rglob("*.template.*"):
    if not template_path.is_file():
        continue
    output_path = Path(str(template_path).replace(".template.", "."))
    text = template_path.read_text()
    keys = tuple(sorted(re.findall(r"{{([A-Z_]+)}}", text)))
    for key in keys:
        text = text.replace("{{" + key + "}}", _g(key))
    output_path.write_text(text)
    print (f"[OK] {output_path}")

