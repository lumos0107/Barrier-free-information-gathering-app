"""공개 전 검사. 저장소에 대상지 자료나 키가 들어가지 않았는지 본다. 실패하면 올리지 않는다.
실행: python -I tools/check_public.py
"""
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 200_000
TEXT = {".js", ".mjs", ".py", ".json", ".md", ".html", ".css", ".sql", ".webmanifest", ".txt"}
LONLAT = re.compile(r"\b1(?:2[4-9]|3[01])\.\d{4,}|\b3[3-8]\.\d{4,}")
SECRET = re.compile(r"sb_secret_[A-Za-z0-9]|sb_publishable_[A-Za-z0-9_-]{12,}|eyJhbGci[A-Za-z0-9_-]{10,}|[a-z]{20}\.supabase\.co|gmail\.com")
BASE64 = re.compile(r"[A-Za-z0-9+/]{2000,}")
ALLOW_LONLAT = {"tools/check_public.py"}


def tracked():
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True)
    return [ROOT / x for x in out.stdout.splitlines() if x]


def main():
    bad = []
    files = tracked()
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        if not p.exists():
            continue
        size = p.stat().st_size
        if size > MAX_BYTES:
            bad.append(f"{rel}: 파일이 큼 ({size} 바이트)")
        if p.suffix.lower() in {".jpg", ".jpeg", ".tif", ".tiff", ".geojson"}:
            bad.append(f"{rel}: 넣으면 안 되는 형식")
        if p.suffix.lower() in TEXT:
            text = p.read_text(encoding="utf-8", errors="ignore")
            if rel not in ALLOW_LONLAT:
                m = LONLAT.search(text)
                if m:
                    bad.append(f"{rel}: 좌표로 보이는 숫자 {m.group(0)}")
                m = SECRET.search(text)
                if m:
                    bad.append(f"{rel}: 키나 주소로 보이는 값 {m.group(0)[:16]}")
                if BASE64.search(text):
                    bad.append(f"{rel}: 긴 base64 자료")
    sw = (ROOT / "docs/sw.js").read_text(encoding="utf-8")
    ver = (ROOT / "docs/js/version.js").read_text(encoding="utf-8")
    a = re.search(r'VERSION = "([^"]+)"', sw).group(1)
    b = re.search(r'APP_VERSION = "([^"]+)"', ver).group(1)
    if a != b:
        bad.append(f"판 번호가 다름: sw.js {a}, version.js {b}")
    listed = set(re.findall(r'"\./([^"]+)"', sw))
    actual = {p.relative_to(ROOT / "docs").as_posix() for p in (ROOT / "docs").rglob("*") if p.is_file()} - {"sw.js"}
    if listed != actual:
        bad.append(f"서비스 워커 파일 목록이 실제와 다름: 빠짐 {sorted(actual - listed)}, 없는 것 {sorted(listed - actual)}")
    print(f"검사 파일 {len(files)}개, 문제 {len(bad)}개")
    for x in bad:
        print("  ", x)
    sys.exit(1 if bad else 0)


main()
