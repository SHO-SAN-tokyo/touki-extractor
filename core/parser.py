"""
core/parser.py
法務局 不動産受付帳 PDF の解析モジュール。

【実PDFから判明したフォーマット仕様 (堺支局 令和8年3月分)】

1エントリ = 3行構成:
  行1: ┃　【第１０１０４号　　　　　　　】　３月　２日受付（単独）　所有権移転・相続　　　　　│
  行2: ┃　既）土地　堺市堺区榎元町一丁１０　　　　　　　　　　　　　　　　　　　　　　　　　│
  行3: ┃　　　　　　　　（空白行）　　　　　　　　　　　　　　　　　　　　　　　　　　　　　│
区切り: ┠──────────────────────────────────┼────┨

特記事項:
- 受付番号フィールドは固定幅 (例: 第１００８０－号 のように末尾にハイフンが付く場合もある)
- 受付日は月と日の間に全角スペースあり (３月　２日受付)
- 申請区分は全角括弧 （単独）（連先）（連続）
- 不動産種別プレフィックスは「既）」または「新）」
- 目的文字列が行1の右端を超えた場合、残りが行2末尾に3スペース以上の空白で区切られて現れる
- 右カラム (│ より右) には空白または目的の末尾continuation が入ることがある

全て純粋関数。副作用なし。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pdfplumber

# ---------------------------------------------------------------------------
# 定数・変換テーブル
# ---------------------------------------------------------------------------

_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
_FULLWIDTH_PARENS = str.maketrans("（）", "()")
_FULLWIDTH_MISC   = str.maketrans("－", "-")   # 全角ハイフン

PROPERTY_TYPES: tuple[str, ...] = ("土地", "建物", "区建", "共担")

# 行1: 受付番号・受付日・申請区分・登記目的
# 例: 【第10104号       】 3月 2日受付(単独) 所有権移転・相続
_LINE1_RE = re.compile(
    r"【第(\d+[-]?)号\s*】"       # グループ1: 受付番号 (ハイフン付きも対応)
    r"\s*(\d+)月\s*(\d+)日受付"   # グループ2: 月, グループ3: 日
    r"[（(]([^）)]+)[）)]"         # グループ4: 申請区分
    r"\s*(.+)"                    # グループ5: 登記目的 (行末まで)
)

# 行2: 不動産種別・所在
# 例: 既）土地 堺市堺区榎元町一丁10
_LINE2_RE = re.compile(
    r"(?:既|新)\)\s*"
    r"(土地|建物|区建|共担)"      # グループ1: 不動産種別
    r"\s+(.*)"                    # グループ2: 所在 + 備考 (後処理で分離)
)

# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------


@dataclass
class ParsedEntry:
    """受付帳の1エントリを表すデータクラス。"""

    receipt_number: str   # 受付番号  例: "第10104号"
    receipt_date: str     # 受付日    例: "3月2日"
    category: str         # 申請区分  例: "単独"
    purpose: str          # 登記目的  例: "所有権移転・相続"
    property_type: str    # 不動産種別 例: "土地"
    location: str         # 所在      例: "堺市堺区榎元町一丁10"
    remarks: str          # 備考      例: "外1"
    source_file: str = "" # 元PDFファイル名 (追跡用)
    raw_line1: str = ""   # デバッグ用生テキスト
    raw_line2: str = ""   # デバッグ用生テキスト


# ---------------------------------------------------------------------------
# 文字列正規化
# ---------------------------------------------------------------------------


def normalize_text(text: str) -> str:
    """全角数字・全角括弧・全角ハイフン・全角スペースを半角に統一し前後空白を除去する。

    Args:
        text: 正規化対象の文字列。

    Returns:
        正規化済み文字列。
    """
    return (
        text.translate(_FULLWIDTH_DIGITS)
            .translate(_FULLWIDTH_PARENS)
            .translate(_FULLWIDTH_MISC)
            .replace("　", " ")   # 全角スペース → 半角
            .strip()
    )


def _strip_line(raw: str) -> str:
    """PDFテキスト行から右カラム(│以降)・罫線文字を除去し正規化する。

    処理順:
      1. 「│」で分割して左カラムのみ取得
      2. 罫線文字 (┃ ┠ ┗ ┏ ━ ─) を除去
      3. normalize_text で全角→半角変換・空白除去

    Args:
        raw: pdfplumber または pdftotext が出力した生テキスト行。

    Returns:
        整形済みテキスト。罫線や右カラムを含まない。
    """
    left = raw.split("│")[0]
    left = re.sub(r"[┃┠┗┏━─┯┷]", "", left)
    return normalize_text(left)


# ---------------------------------------------------------------------------
# 行パーサ
# ---------------------------------------------------------------------------


def parse_line1(raw: str) -> Optional[dict[str, str]]:
    """受付帳の1行目 (受付番号・受付日・申請区分・登記目的) を解析する。

    期待フォーマット (正規化後):
        【第10104号       】 3月 2日受付(単独) 所有権移転・相続

    登記目的が列幅を超えた場合は行末で切れる場合があります。
    完全な目的文字列は行2末尾の overflow テキストと連結する必要がありますが、
    MVP では行1に記載された分のみを取得します。

    Args:
        raw: PDFから抽出した生テキスト1行。

    Returns:
        {"receipt_number", "receipt_date", "category", "purpose"} の辞書。
        パターンに一致しない場合は None。
    """
    line = _strip_line(raw)
    m = _LINE1_RE.search(line)
    if m is None:
        return None

    raw_num = m.group(1)   # "10104" or "10080-"

    return {
        "receipt_number": f"第{raw_num}号",
        "receipt_date": f"{m.group(2)}月{m.group(3)}日",
        "category": m.group(4).strip(),
        "purpose": m.group(5).strip(),
    }


def _split_location_remarks(rest: str) -> tuple[str, str]:
    """所在文字列から所在と備考 (外X) を分離する。

    分離ルール:
      1. 3文字以上の連続スペースで分割し、最初のブロックを主要部とする
         (行2末尾のoverflowテキストを切り捨てる)
      2. 主要部の中で「 外\\d+」パターンを探して所在と備考を分離する

    Args:
        rest: LINE2_RE グループ2 の文字列 (正規化済み)。

    Returns:
        (location, remarks) のタプル。
    """
    # overflow テキスト (3スペース以上で区切られた末尾) を除去
    main_part = re.split(r" {3,}", rest.strip())[0].strip()

    # 「 外X」で所在と備考を分離
    soto_m = re.search(r" (外\d+\S*)", main_part)
    if soto_m:
        location = main_part[: soto_m.start()].strip()
        remarks = soto_m.group(1).strip()
    else:
        location = main_part
        remarks = ""

    return location, remarks


def parse_line2(raw: str) -> Optional[dict[str, str]]:
    """受付帳の2行目 (不動産種別・所在・備考) を解析する。

    期待フォーマット (正規化後):
        既）土地 堺市北区金岡町1100-29 外1
        新）建物 大阪狭山市西山台2丁目88-360

    目的のoverflow テキストが末尾に続く場合:
        既）土地 堺市西区浜寺石津町西四丁204-77 外1   の変更・更正

    Args:
        raw: PDFから抽出した生テキスト1行。

    Returns:
        {"property_type", "location", "remarks"} の辞書。
        パターンに一致しない場合は None。
    """
    line = _strip_line(raw)
    m = _LINE2_RE.search(line)
    if m is None:
        return None

    location, remarks = _split_location_remarks(m.group(2))

    return {
        "property_type": m.group(1),
        "location": location,
        "remarks": remarks,
    }


# ---------------------------------------------------------------------------
# エントリ組み立て
# ---------------------------------------------------------------------------


def pair_lines(lines: list[str]) -> list[tuple[str, str]]:
    """テキスト行リストから (行1, 行2) のペアを抽出する。

    行1の判定基準: 正規化後のテキストに「【第」＋数字が含まれること。
    行1を見つけたら直後の行を行2として組み合わせる。
    3行目 (空白行) と罫線行は自動的にスキップされる。

    Args:
        lines: PDFから抽出した全テキスト行。

    Returns:
        (行1文字列, 行2文字列) のタプルリスト。
    """
    pairs: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        stripped = _strip_line(lines[i])
        if re.search(r"【第\d+", stripped):
            if i + 1 < len(lines):
                pairs.append((lines[i], lines[i + 1]))
                i += 2
            else:
                i += 1
        else:
            i += 1
    return pairs


def parse_entries(
    lines: list[str],
    source_file: str = "",
) -> list[ParsedEntry]:
    """テキスト行リストから ParsedEntry のリストを生成する。

    Args:
        lines: PDF1ページ分またはファイル全体のテキスト行リスト。
        source_file: 元PDFのファイル名 (追跡用)。

    Returns:
        パース成功したエントリのリスト。失敗行はスキップ。
    """
    entries: list[ParsedEntry] = []

    for raw1, raw2 in pair_lines(lines):
        d1 = parse_line1(raw1)
        d2 = parse_line2(raw2)

        if d1 is None or d2 is None:
            continue

        entries.append(
            ParsedEntry(
                receipt_number=d1["receipt_number"],
                receipt_date=d1["receipt_date"],
                category=d1["category"],
                purpose=d1["purpose"],
                property_type=d2["property_type"],
                location=d2["location"],
                remarks=d2["remarks"],
                source_file=source_file,
                raw_line1=raw1,
                raw_line2=raw2,
            )
        )

    return entries


# ---------------------------------------------------------------------------
# PDF読み込み
# ---------------------------------------------------------------------------


def extract_lines_from_pdf(pdf_path: Path) -> list[str]:
    """PDFファイルの全ページからテキスト行を抽出する。

    Args:
        pdf_path: 読み込み対象のPDFファイルパス。

    Returns:
        全ページのテキスト行を連結したリスト。

    Raises:
        FileNotFoundError: ファイルが存在しない場合。
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    lines: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=3, y_tolerance=3)
            if text:
                lines.extend(text.splitlines())

    return lines


def parse_pdf(pdf_path: Path) -> list[ParsedEntry]:
    """PDFファイルを解析して ParsedEntry のリストを返す。

    Args:
        pdf_path: 解析対象のPDFファイルパス。

    Returns:
        抽出されたエントリのリスト。
    """
    lines = extract_lines_from_pdf(pdf_path)
    return parse_entries(lines, source_file=pdf_path.name)


def parse_pdfs(pdf_paths: list[Path]) -> list[ParsedEntry]:
    """複数PDFを順次解析してエントリを結合して返す。

    Args:
        pdf_paths: 解析対象PDFのパスリスト。

    Returns:
        全ファイルのエントリを結合したリスト。
    """
    all_entries: list[ParsedEntry] = []
    for path in pdf_paths:
        all_entries.extend(parse_pdf(path))
    return all_entries
