"""
tests/test_filter.py
core/filter.py のユニットテスト。
"""

from pathlib import Path

import pytest

from core.filter import (
    apply_filters,
    filter_by_categories,
    filter_by_municipalities,
    filter_by_property_types,
    filter_by_purposes,
    load_municipalities,
)
from core.parser import ParsedEntry


# ---------------------------------------------------------------------------
# テスト用フィクスチャ
# ---------------------------------------------------------------------------


def _e(
    *,
    receipt_number: str = "第10000号",
    receipt_date: str = "3月1日",
    category: str = "単独",
    purpose: str = "所有権移転・相続",
    property_type: str = "土地",
    location: str = "堺市堺区榎元町一丁10",
    remarks: str = "",
) -> ParsedEntry:
    """テスト用 ParsedEntry を簡易生成するヘルパー。"""
    return ParsedEntry(
        receipt_number=receipt_number,
        receipt_date=receipt_date,
        category=category,
        purpose=purpose,
        property_type=property_type,
        location=location,
        remarks=remarks,
    )


# 実PDFから取得したエントリに近いテストデータセット
_ENTRIES: list[ParsedEntry] = [
    # 0: 相続 / 土地 / 堺市堺区 / 単独
    _e(receipt_number="第10104号", purpose="所有権移転・相続",
       property_type="土地", location="堺市堺区榎元町一丁10", category="単独"),
    # 1: 相続 / 土地 / 堺市北区 / 単独 / 外1
    _e(receipt_number="第10114号", purpose="所有権移転・相続",
       property_type="土地", location="堺市北区金岡町1100-29", remarks="外1"),
    # 2: 相続 / 建物 / 堺市南区 / 単独
    _e(receipt_number="第10105号", purpose="所有権移転・相続",
       property_type="建物", location="堺市南区三原台一丁10-9-2"),
    # 3: 売買 / 土地 / 松原市 / 単独
    _e(receipt_number="第10109号", purpose="所有権移転売買",
       property_type="土地", location="松原市天美東1丁目66-18"),
    # 4: 抵当権設定 / 土地 / 堺市北区 / 単独
    _e(receipt_number="第10093号", purpose="抵当権の設定",
       property_type="土地", location="堺市北区百舌鳥梅町三丁31-13"),
    # 5: 抵当権設定 / 建物 / 大阪狭山市 / 連続
    _e(receipt_number="第10080-号", purpose="抵当権の設定",
       property_type="建物", location="大阪狭山市東茱木2丁目1869-48-2",
       category="連続", remarks="外1"),
    # 6: その他 / 共担 / 堺市 / 単独
    _e(receipt_number="第10075号", purpose="共同担保追加通知",
       property_type="共担", location="8019"),
    # 7: 相続 / 土地 / 堺市西区 / 連先
    _e(receipt_number="第10124号", purpose="所有権移転・相続",
       property_type="土地", location="堺市西区浜寺諏訪森町西四丁306-5",
       category="連先", remarks="外1"),
    # 8: その他 / 土地 / 松原市 / 単独 (登記名義人変更)
    _e(receipt_number="第10078号", purpose="登記名義人の氏名等についての変更・更正",
       property_type="土地", location="松原市天美北7丁目321"),
    # 9: 売買 / 土地 / 高石市 / 単独
    _e(receipt_number="第20001号", purpose="所有権移転売買",
       property_type="土地", location="高石市綾園5丁目1-1"),
]


# ---------------------------------------------------------------------------
# filter_by_municipalities
# ---------------------------------------------------------------------------


class TestFilterByMunicipalities:
    def test_single_match(self):
        result = filter_by_municipalities(_ENTRIES, ["松原市"])
        assert len(result) == 2
        assert all(e.location.startswith("松原市") for e in result)

    def test_multi_match(self):
        result = filter_by_municipalities(_ENTRIES, ["堺市堺区", "堺市北区"])
        numbers = {e.receipt_number for e in result}
        assert "第10104号" in numbers   # 堺市堺区
        assert "第10114号" in numbers   # 堺市北区 (金岡町)
        assert "第10093号" in numbers   # 堺市北区 (百舌鳥)

    def test_district_match_excludes_other_districts(self):
        """堺市堺区 を指定したとき 堺市北区 は含まれない。"""
        result = filter_by_municipalities(_ENTRIES, ["堺市堺区"])
        assert all(e.location.startswith("堺市堺区") for e in result)
        assert not any(e.location.startswith("堺市北区") for e in result)

    def test_city_level_matches_all_districts(self):
        """「堺市」で絞ると 堺市XX区 を全て拾う。"""
        result = filter_by_municipalities(_ENTRIES, ["堺市"])
        assert all(e.location.startswith("堺市") for e in result)

    def test_empty_list_returns_all(self):
        assert filter_by_municipalities(_ENTRIES, []) == _ENTRIES

    def test_no_match_returns_empty(self):
        assert filter_by_municipalities(_ENTRIES, ["東大阪市"]) == []

    def test_kyotan_location_number_not_matched(self):
        """共担の location は参照番号なので市区町村にはマッチしない。"""
        result = filter_by_municipalities(_ENTRIES, ["堺市"])
        assert all(e.property_type != "共担" for e in result)


# ---------------------------------------------------------------------------
# filter_by_categories
# ---------------------------------------------------------------------------


class TestFilterByCategories:
    def test_single_category(self):
        result = filter_by_categories(_ENTRIES, ["単独"])
        assert all(e.category == "単独" for e in result)

    def test_multi_category(self):
        result = filter_by_categories(_ENTRIES, ["連先", "連続"])
        assert all(e.category in ("連先", "連続") for e in result)

    def test_empty_list_returns_all(self):
        assert filter_by_categories(_ENTRIES, []) == _ENTRIES

    def test_no_match(self):
        assert filter_by_categories(_ENTRIES, ["嘱託"]) == []

    def test_count_rensaki(self):
        result = filter_by_categories(_ENTRIES, ["連先"])
        assert len(result) == 1
        assert result[0].receipt_number == "第10124号"


# ---------------------------------------------------------------------------
# filter_by_purposes
# ---------------------------------------------------------------------------


class TestFilterByPurposes:
    def test_souzoku(self):
        result = filter_by_purposes(_ENTRIES, ["相続"])
        assert all("相続" in e.purpose for e in result)
        assert len(result) == 4  # 0,1,2,7

    def test_baibai(self):
        result = filter_by_purposes(_ENTRIES, ["売買"])
        assert all("売買" in e.purpose for e in result)
        assert len(result) == 2  # 3,9

    def test_teitouken(self):
        result = filter_by_purposes(_ENTRIES, ["抵当権設定"])
        assert all("抵当権" in e.purpose for e in result)
        assert len(result) == 2  # 4,5

    def test_sonota(self):
        """「その他」は相続/売買/抵当権のいずれも含まないエントリ。"""
        result = filter_by_purposes(_ENTRIES, ["その他"])
        for e in result:
            assert "相続" not in e.purpose
            assert "売買" not in e.purpose
            assert "抵当権" not in e.purpose

    def test_sonota_count(self):
        result = filter_by_purposes(_ENTRIES, ["その他"])
        assert len(result) == 2  # 6(共同担保追加通知), 8(登記名義人変更)

    def test_or_condition(self):
        """相続 OR 売買 → 6件。"""
        result = filter_by_purposes(_ENTRIES, ["相続", "売買"])
        assert len(result) == 6

    def test_all_labels(self):
        """全ラベル選択 → 全件。"""
        result = filter_by_purposes(_ENTRIES, ["相続", "売買", "抵当権設定", "その他"])
        assert len(result) == len(_ENTRIES)

    def test_empty_list_returns_all(self):
        assert filter_by_purposes(_ENTRIES, []) == _ENTRIES


# ---------------------------------------------------------------------------
# filter_by_property_types
# ---------------------------------------------------------------------------


class TestFilterByPropertyTypes:
    def test_tochi_only(self):
        result = filter_by_property_types(_ENTRIES, ["土地"])
        assert all(e.property_type == "土地" for e in result)

    def test_tatemono_only(self):
        result = filter_by_property_types(_ENTRIES, ["建物"])
        assert all(e.property_type == "建物" for e in result)

    def test_kyotan_only(self):
        result = filter_by_property_types(_ENTRIES, ["共担"])
        assert len(result) == 1
        assert result[0].receipt_number == "第10075号"

    def test_tochi_and_tatemono(self):
        result = filter_by_property_types(_ENTRIES, ["土地", "建物"])
        assert all(e.property_type in ("土地", "建物") for e in result)

    def test_empty_list_returns_all(self):
        assert filter_by_property_types(_ENTRIES, []) == _ENTRIES

    def test_no_match(self):
        assert filter_by_property_types(_ENTRIES, ["区建"]) == []


# ---------------------------------------------------------------------------
# apply_filters (統合)
# ---------------------------------------------------------------------------


class TestApplyFilters:
    def test_souzoku_tochi_sakai(self):
        """相続 × 土地 × 堺市 → 3件 (堺区・北区・西区)。"""
        result = apply_filters(
            _ENTRIES,
            municipalities=["堺市"],
            purpose_labels=["相続"],
            property_types=["土地"],
        )
        assert len(result) == 3
        assert all("相続" in e.purpose for e in result)
        assert all(e.property_type == "土地" for e in result)
        assert all(e.location.startswith("堺市") for e in result)

    def test_all_none_returns_all(self):
        assert apply_filters(_ENTRIES) == _ENTRIES

    def test_empty_lists_returns_all(self):
        result = apply_filters(
            _ENTRIES,
            municipalities=[],
            categories=[],
            purpose_labels=[],
            property_types=[],
        )
        assert result == _ENTRIES

    def test_no_results_combination(self):
        """建物 × 堺市堺区 → 0件 (堺市堺区に建物エントリなし)。"""
        result = apply_filters(
            _ENTRIES,
            municipalities=["堺市堺区"],
            property_types=["建物"],
        )
        assert result == []

    def test_category_and_purpose(self):
        """連先 × 相続 → 第10124号のみ。"""
        result = apply_filters(
            _ENTRIES,
            categories=["連先"],
            purpose_labels=["相続"],
        )
        assert len(result) == 1
        assert result[0].receipt_number == "第10124号"

    def test_order_preserved(self):
        """フィルタ後も元の順序が保持される。"""
        result = apply_filters(_ENTRIES, purpose_labels=["相続"])
        numbers = [e.receipt_number for e in result]
        # 元リスト (_ENTRIES) での相続エントリの順序
        expected = ["第10104号", "第10114号", "第10105号", "第10124号"]
        assert numbers == expected


# ---------------------------------------------------------------------------
# load_municipalities
# ---------------------------------------------------------------------------


class TestLoadMunicipalities:
    def test_returns_list(self):
        yaml_path = Path(__file__).parents[1] / "config" / "prefectures.yaml"
        muns = load_municipalities(yaml_path)
        assert isinstance(muns, list)
        assert len(muns) > 0

    def test_contains_osaka_city_wards(self):
        yaml_path = Path(__file__).parents[1] / "config" / "prefectures.yaml"
        muns = load_municipalities(yaml_path)
        assert "大阪市北区" in muns
        assert "大阪市天王寺区" in muns

    def test_contains_sakai_districts(self):
        yaml_path = Path(__file__).parents[1] / "config" / "prefectures.yaml"
        muns = load_municipalities(yaml_path)
        for district in ["堺市堺区", "堺市中区", "堺市東区",
                         "堺市西区", "堺市南区", "堺市北区", "堺市美原区"]:
            assert district in muns, f"{district} が YAML に含まれていない"

    def test_contains_sample_pdf_municipalities(self):
        """実PDFに出てきた市区町村が全て含まれること。"""
        yaml_path = Path(__file__).parents[1] / "config" / "prefectures.yaml"
        muns = load_municipalities(yaml_path)
        for m in ["松原市", "大阪狭山市", "高石市"]:
            assert m in muns, f"{m} が YAML に含まれていない"

    def test_no_duplicates(self):
        yaml_path = Path(__file__).parents[1] / "config" / "prefectures.yaml"
        muns = load_municipalities(yaml_path)
        assert len(muns) == len(set(muns)), "重複エントリあり"
