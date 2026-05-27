"""
core/filter.py
ParsedEntry リストへの絞り込みロジック。

全て純粋関数。副作用なし。
各フィルタは独立して呼び出せる。apply_filters() で一括適用。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from core.parser import ParsedEntry

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

# 登記目的ラベル → 部分一致キーワード
# "その他" は主要3カテゴリのいずれにも該当しない場合に選択されたとみなす
_PURPOSE_KEYWORD_MAP: dict[str, str] = {
    "相続":      "相続",
    "売買":      "売買",
    "抵当権設定": "抵当権",
    "その他":    "",   # 特殊処理
}

# 主要カテゴリのキーワード一覧 (「その他」判定に使用)
_MAJOR_PURPOSE_KEYWORDS: tuple[str, ...] = ("相続", "売買", "抵当権")


# ---------------------------------------------------------------------------
# 個別フィルタ
# ---------------------------------------------------------------------------


def filter_by_municipalities(
    entries: list[ParsedEntry],
    municipalities: list[str],
) -> list[ParsedEntry]:
    """所在が指定した市区町村のいずれかで始まるエントリのみを返す。

    大阪市の区など「大阪市北区」のように区まで指定すると精度が上がる。
    空リストを渡した場合はフィルタなしで全件返す。

    Args:
        entries: フィルタ対象のエントリリスト。
        municipalities: 絞り込む市区町村名のリスト。

    Returns:
        条件に一致したエントリのリスト。
    """
    if not municipalities:
        return entries
    return [
        e for e in entries
        if any(e.location.startswith(m) for m in municipalities)
    ]


def filter_by_categories(
    entries: list[ParsedEntry],
    categories: list[str],
) -> list[ParsedEntry]:
    """申請区分が一致するエントリのみを返す。

    Args:
        entries: フィルタ対象のエントリリスト。
        categories: 絞り込む申請区分のリスト (例: ["単独", "連先"])。

    Returns:
        条件に一致したエントリのリスト。
    """
    if not categories:
        return entries
    return [e for e in entries if e.category in categories]


def filter_by_purposes(
    entries: list[ParsedEntry],
    purpose_labels: list[str],
) -> list[ParsedEntry]:
    """登記目的ラベルで絞り込んだエントリを返す。

    ラベルと照合ルール:
      - "相続"      → purpose に "相続" を含む
      - "売買"      → purpose に "売買" を含む
      - "抵当権設定" → purpose に "抵当権" を含む
      - "その他"    → purpose に (相続/売買/抵当権) のいずれも含まない

    複数ラベルを指定した場合はOR条件。
    空リストを渡した場合はフィルタなしで全件返す。

    Args:
        entries: フィルタ対象のエントリリスト。
        purpose_labels: 絞り込むラベルのリスト。

    Returns:
        条件に一致したエントリのリスト。
    """
    if not purpose_labels:
        return entries

    result: list[ParsedEntry] = []
    for entry in entries:
        if _matches_purpose(entry.purpose, purpose_labels):
            result.append(entry)
    return result


def _matches_purpose(purpose: str, labels: list[str]) -> bool:
    """登記目的文字列がラベルリストのいずれかにマッチするか判定する。

    Args:
        purpose: 判定対象の登記目的文字列。
        labels: 判定するラベルのリスト。

    Returns:
        いずれかのラベルにマッチすれば True。
    """
    for label in labels:
        if label == "その他":
            if not any(kw in purpose for kw in _MAJOR_PURPOSE_KEYWORDS):
                return True
        else:
            keyword = _PURPOSE_KEYWORD_MAP.get(label, label)
            if keyword and keyword in purpose:
                return True
    return False


def filter_by_property_types(
    entries: list[ParsedEntry],
    property_types: list[str],
) -> list[ParsedEntry]:
    """不動産種別が一致するエントリのみを返す。

    Args:
        entries: フィルタ対象のエントリリスト。
        property_types: 絞り込む種別のリスト (例: ["土地", "建物"])。

    Returns:
        条件に一致したエントリのリスト。
    """
    if not property_types:
        return entries
    return [e for e in entries if e.property_type in property_types]


# ---------------------------------------------------------------------------
# 一括適用
# ---------------------------------------------------------------------------


def apply_filters(
    entries: list[ParsedEntry],
    municipalities: Optional[list[str]] = None,
    categories: Optional[list[str]] = None,
    purpose_labels: Optional[list[str]] = None,
    property_types: Optional[list[str]] = None,
) -> list[ParsedEntry]:
    """全フィルタを順次AND条件で適用する。

    None または空リストを渡したフィルタはスキップ (全件通過)。

    Args:
        entries: フィルタ対象のエントリリスト。
        municipalities: 市区町村フィルタ。
        categories: 申請区分フィルタ。
        purpose_labels: 登記目的フィルタ。
        property_types: 不動産種別フィルタ。

    Returns:
        全フィルタを通過したエントリのリスト。
    """
    result = entries
    if municipalities:
        result = filter_by_municipalities(result, municipalities)
    if categories:
        result = filter_by_categories(result, categories)
    if purpose_labels:
        result = filter_by_purposes(result, purpose_labels)
    if property_types:
        result = filter_by_property_types(result, property_types)
    return result


# ---------------------------------------------------------------------------
# YAML ユーティリティ
# ---------------------------------------------------------------------------


def load_municipalities(yaml_path: Path, prefecture: str = "osaka") -> list[str]:
    """prefectures.yaml から市区町村リストを読み込む。

    Args:
        yaml_path: prefectures.yaml のパス。
        prefecture: YAMLのトップキー (デフォルト: "osaka")。

    Returns:
        市区町村名のリスト。
    """
    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data[prefecture]["municipalities"]
