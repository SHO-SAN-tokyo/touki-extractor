"""
tests/test_parser.py
core/parser.py のユニットテスト。

テストデータは 堺支局_令和8年3月分.pdf から取得した実際のテキスト行を使用。
"""

import pytest

from core.parser import (
    ParsedEntry,
    _split_location_remarks,
    _strip_line,
    normalize_text,
    pair_lines,
    parse_entries,
    parse_line1,
    parse_line2,
)

# ---------------------------------------------------------------------------
# 実PDFから取得した生テキスト行 (定数として定義)
# ---------------------------------------------------------------------------

# 第10104号 - 所有権移転・相続 / 土地 (備考なし)
_RAW_L1_SOUZOKU_TOCHI = "　　┃　【第１０１０４号　　　　　　　】　３月　２日受付（単独）　所有権移転・相続　　　　　│　　　　┃"
_RAW_L2_SOUZOKU_TOCHI = "　　┃　既）土地　堺市堺区榎元町一丁１０　　　　　　　　　　　　　　　　　　　　　　　　　│　　　　┃"

# 第10114号 - 所有権移転・相続 / 土地 外1
_RAW_L1_SOUZOKU_GAICHI = "　　┃　【第１０１１４号　　　　　　　】　３月　２日受付（単独）　所有権移転・相続　　　　　│　　　　┃"
_RAW_L2_SOUZOKU_GAICHI = "　　┃　既）土地　堺市北区金岡町１１００－２９　外１　　　　　　　　　　　　　　　　　　　　│　　　　┃"

# 第10076号 - 目的overflowあり / 建物 外1
_RAW_L1_OVERFLOW = "　　┃　【第１００７６号　　　　　　　】　３月　２日受付（単独）　表示に関するその他／オン・│　　　　┃"
_RAW_L2_OVERFLOW = "　　┃　既）建物　堺市北区百舌鳥梅町三丁１３－１６－２　外１　　　表示　　　　　　　　　　│　　　　┃"

# 第10075号 - 共担 (所在なし)
_RAW_L1_KYOTAN = "　　┃　【第１００７５号　　　　　　　】　３月　２日受付（単独）　共同担保追加通知　　　　　│　　　　┃"
_RAW_L2_KYOTAN = "　　┃　既）共担　８０１９　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　│　　　　┃"

# 第10080-号 - ハイフン付き受付番号 / 連続
_RAW_L1_HYPHEN = "　　┃　【第１００８０－号　　　　　】　３月　２日受付（連続）　抵当権の設定　　　　　　　│　　　　┃"
_RAW_L2_HYPHEN = "　　┃　既）建物　大阪狭山市東茱木２丁目１８６９－４８－２　外１　　　　　　　　　　　　　│　　　　┃"

# 第10118号 - 新）建物
_RAW_L1_SHIN = "　　┃　【第１０１１８号　　　　　　　】　３月　２日受付（単独）　表題／オン・表示　　　　　│　　　　┃"
_RAW_L2_SHIN = "　　┃　新）建物　大阪狭山市西山台２丁目８８－３６０　　　　　　　　　　　　　　　　　　　　│　　　　┃"

# 第10115号 - 登記目的overflow (外1 あり, overflow = "の変更・更正")
_RAW_L1_NAGAMOKU = "　　┃　【第１０１１５号　　　　　　　】　３月　２日受付（連先）　登記名義人の氏名等について│　　　　┃"
_RAW_L2_NAGAMOKU = "　　┃　既）土地　堺市西区浜寺石津町西四丁２０４－７７　外１　　　の変更・更正　　　　　　　│　　　　┃"

# 第10124号 - 所有権移転・相続 / 土地 外1 / 連先
_RAW_L1_RENSAKISOUZOKU = "　　┃　【第１０１２４号　　　　　　　】　３月　２日受付（連先）　所有権移転・相続　　　　　│　　　　┃"
_RAW_L2_RENSAKISOUZOKU = "　　┃　既）土地　堺市西区浜寺諏訪森町西四丁３０６－５　外１　　　　　　　　　　　　　　　　│　　　　┃"


# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------


class TestNormalizeText:
    def test_fullwidth_digits(self):
        assert normalize_text("第１０１０４号") == "第10104号"

    def test_fullwidth_parens(self):
        assert normalize_text("（単独）") == "(単独)"

    def test_fullwidth_hyphen(self):
        assert normalize_text("１０８０－号") == "1080-号"

    def test_ideographic_space(self):
        assert normalize_text("３月　２日") == "3月 2日"

    def test_strips_whitespace(self):
        assert normalize_text("  hello  ") == "hello"

    def test_combined(self):
        result = normalize_text("【第１０１０４号　　　　　　　】　３月　２日受付（単独）")
        assert result == "【第10104号       】 3月 2日受付(単独)"


# ---------------------------------------------------------------------------
# _strip_line
# ---------------------------------------------------------------------------


class TestStripLine:
    def test_removes_right_column(self):
        raw = "┃　【第１０１０４号　　　　　　　】　３月　２日受付（単独）　所有権移転・相続　　　　　│　　　　┃"
        result = _strip_line(raw)
        assert "│" not in result
        assert "┃" not in result

    def test_normalizes_fullwidth(self):
        raw = "　　┃　【第１０１０４号　　　　　　　】　３月　２日受付（単独）　所有権移転・相続　　　　　│　　　　┃"
        result = _strip_line(raw)
        assert "【第10104号" in result
        assert "(単独)" in result

    def test_strips_leading_trailing(self):
        result = _strip_line(_RAW_L1_SOUZOKU_TOCHI)
        assert not result.startswith(" ")
        assert not result.endswith(" ")


# ---------------------------------------------------------------------------
# parse_line1
# ---------------------------------------------------------------------------


class TestParseLine1:

    # --- 正常系: 実PDFデータ ---

    def test_souzoku_basic(self):
        """相続エントリ (備考なし)。"""
        r = parse_line1(_RAW_L1_SOUZOKU_TOCHI)
        assert r is not None
        assert r["receipt_number"] == "第10104号"
        assert r["receipt_date"] == "3月2日"
        assert r["category"] == "単独"
        assert r["purpose"] == "所有権移転・相続"

    def test_souzoku_rensaki(self):
        """相続・連先エントリ。"""
        r = parse_line1(_RAW_L1_RENSAKISOUZOKU)
        assert r is not None
        assert r["receipt_number"] == "第10124号"
        assert r["category"] == "連先"
        assert r["purpose"] == "所有権移転・相続"

    def test_hyphen_receipt_number(self):
        """ハイフン付き受付番号 (第10080-号)。"""
        r = parse_line1(_RAW_L1_HYPHEN)
        assert r is not None
        assert r["receipt_number"] == "第10080-号"
        assert r["category"] == "連続"

    def test_purpose_overflow_truncated(self):
        """登記目的が列幅を超えて切れている行。切れた部分は含まない。"""
        r = parse_line1(_RAW_L1_OVERFLOW)
        assert r is not None
        assert r["receipt_number"] == "第10076号"
        assert "表示に関するその他" in r["purpose"]

    def test_kyotan_entry(self):
        """共担エントリ。"""
        r = parse_line1(_RAW_L1_KYOTAN)
        assert r is not None
        assert r["receipt_number"] == "第10075号"
        assert r["purpose"] == "共同担保追加通知"

    def test_shin_tatemono(self):
        """新）建物エントリの行1。"""
        r = parse_line1(_RAW_L1_SHIN)
        assert r is not None
        assert r["receipt_number"] == "第10118号"

    def test_receipt_date_no_space(self):
        """受付日に月・日間スペースがあっても 'X月Y日' でまとめる。"""
        r = parse_line1(_RAW_L1_SOUZOKU_TOCHI)
        assert r is not None
        assert r["receipt_date"] == "3月2日"   # スペースなし

    # --- 異常系 ---

    def test_returns_none_for_line2_content(self):
        assert parse_line1(_RAW_L2_SOUZOKU_TOCHI) is None

    def test_returns_none_for_empty_line(self):
        assert parse_line1("") is None

    def test_returns_none_for_separator(self):
        assert parse_line1("　　┠───────────────────────────────────────────┼────┨") is None

    def test_returns_none_for_page_header(self):
        assert parse_line1("　　　　　＊受付帳　＜不動産＞") is None


# ---------------------------------------------------------------------------
# parse_line2
# ---------------------------------------------------------------------------


class TestParseLine2:

    # --- 正常系: 実PDFデータ ---

    def test_tochi_no_remarks(self):
        """土地・備考なし。"""
        r = parse_line2(_RAW_L2_SOUZOKU_TOCHI)
        assert r is not None
        assert r["property_type"] == "土地"
        assert r["location"] == "堺市堺区榎元町一丁10"
        assert r["remarks"] == ""

    def test_tochi_with_gaichi(self):
        """土地・外1あり。"""
        r = parse_line2(_RAW_L2_SOUZOKU_GAICHI)
        assert r is not None
        assert r["property_type"] == "土地"
        assert r["location"] == "堺市北区金岡町1100-29"
        assert r["remarks"] == "外1"

    def test_tochi_gaichi_with_overflow(self):
        """外1あり + 登記目的overflow ("の変更・更正")。overflowは所在に混入しない。"""
        r = parse_line2(_RAW_L2_NAGAMOKU)
        assert r is not None
        assert r["property_type"] == "土地"
        assert r["location"] == "堺市西区浜寺石津町西四丁204-77"
        assert r["remarks"] == "外1"

    def test_tatemono_gaichi_with_overflow(self):
        """建物・外1あり + 目的overflow。"""
        r = parse_line2(_RAW_L2_OVERFLOW)
        assert r is not None
        assert r["property_type"] == "建物"
        assert r["location"] == "堺市北区百舌鳥梅町三丁13-16-2"
        assert r["remarks"] == "外1"

    def test_shin_tatemono(self):
        """新）建物プレフィックス。"""
        r = parse_line2(_RAW_L2_SHIN)
        assert r is not None
        assert r["property_type"] == "建物"
        assert r["location"] == "大阪狭山市西山台2丁目88-360"
        assert r["remarks"] == ""

    def test_kyotan_reference_number(self):
        """共担エントリ (所在が参照番号)。"""
        r = parse_line2(_RAW_L2_KYOTAN)
        assert r is not None
        assert r["property_type"] == "共担"
        assert r["location"] == "8019"

    def test_rensaki_souzoku_gaichi(self):
        """連先・相続・外1あり。"""
        r = parse_line2(_RAW_L2_RENSAKISOUZOKU)
        assert r is not None
        assert r["property_type"] == "土地"
        assert r["location"] == "堺市西区浜寺諏訪森町西四丁306-5"
        assert r["remarks"] == "外1"

    # --- 異常系 ---

    def test_returns_none_for_line1_content(self):
        assert parse_line2(_RAW_L1_SOUZOKU_TOCHI) is None

    def test_returns_none_for_empty_line(self):
        assert parse_line2("") is None

    def test_returns_none_for_separator(self):
        assert parse_line2("　　┠────────────────────────────┼────┨") is None


# ---------------------------------------------------------------------------
# _split_location_remarks
# ---------------------------------------------------------------------------


class TestSplitLocationRemarks:
    """_split_location_remarks の単体テスト (正規化済み文字列を想定)。"""

    def test_no_gaichi(self):
        loc, rem = _split_location_remarks("堺市堺区榎元町一丁10")
        assert loc == "堺市堺区榎元町一丁10"
        assert rem == ""

    def test_gaichi_1(self):
        loc, rem = _split_location_remarks("堺市北区金岡町1100-29 外1")
        assert loc == "堺市北区金岡町1100-29"
        assert rem == "外1"

    def test_gaichi_2(self):
        loc, rem = _split_location_remarks("大阪狭山市狭山3丁目100-21 外2")
        assert loc == "大阪狭山市狭山3丁目100-21"
        assert rem == "外2"

    def test_overflow_stripped(self):
        """3スペース以上のgapで区切られたoverflowテキストは所在に含まれない。"""
        loc, rem = _split_location_remarks("堺市西区浜寺石津町西四丁204-77 外1   の変更・更正")
        assert loc == "堺市西区浜寺石津町西四丁204-77"
        assert rem == "外1"

    def test_overflow_no_gaichi(self):
        """外Xがなくoverflowのみの場合、overflowは除去される。"""
        loc, rem = _split_location_remarks("堺市北区百舌鳥赤畑町五丁490-2       の変更・更正")
        assert loc == "堺市北区百舌鳥赤畑町五丁490-2"
        assert rem == ""


# ---------------------------------------------------------------------------
# pair_lines
# ---------------------------------------------------------------------------


class TestPairLines:
    def test_single_entry(self):
        pairs = pair_lines([_RAW_L1_SOUZOKU_TOCHI, _RAW_L2_SOUZOKU_TOCHI])
        assert len(pairs) == 1

    def test_two_entries_with_blank_and_separator(self):
        """実際のPDF構造: 行1・行2・空白行・区切り行 x2エントリ。"""
        lines = [
            _RAW_L1_SOUZOKU_TOCHI,
            _RAW_L2_SOUZOKU_TOCHI,
            "　　┃　　　　　　　　　　　　　　　│　　　　┃",  # 空白行
            "　　┠───────────────────────────────────────────┼────┨",  # 区切り
            _RAW_L1_SOUZOKU_GAICHI,
            _RAW_L2_SOUZOKU_GAICHI,
            "　　┃　　　　　　　　　　　　　　　│　　　　┃",
        ]
        pairs = pair_lines(lines)
        assert len(pairs) == 2

    def test_skip_page_header(self):
        """ページヘッダー行 (受付帳タイトルなど) はスキップ。"""
        lines = [
            "　　　　　＊受付帳　＜不動産＞",
            "　　　令和　８年",
            "　　┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┯━━━━┓",
            _RAW_L1_SOUZOKU_TOCHI,
            _RAW_L2_SOUZOKU_TOCHI,
        ]
        pairs = pair_lines(lines)
        assert len(pairs) == 1

    def test_empty_input(self):
        assert pair_lines([]) == []

    def test_hyphen_receipt_number_detected(self):
        """ハイフン付き受付番号 (第10080-号) も行1として検出される。"""
        pairs = pair_lines([_RAW_L1_HYPHEN, _RAW_L2_HYPHEN])
        assert len(pairs) == 1


# ---------------------------------------------------------------------------
# parse_entries (統合テスト)
# ---------------------------------------------------------------------------


class TestParseEntries:
    def _real_lines(self) -> list[str]:
        """実PDFに近い3エントリのテストデータ。"""
        return [
            "　　　　　＊受付帳　＜不動産＞",
            "　　┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┯━━━━┓",
            _RAW_L1_SOUZOKU_TOCHI,
            _RAW_L2_SOUZOKU_TOCHI,
            "　　┃　　　　　　　　　　│　　　　┃",
            "　　┠───────────────────────────────────────────┼────┨",
            _RAW_L1_SOUZOKU_GAICHI,
            _RAW_L2_SOUZOKU_GAICHI,
            "　　┃　　　　　　　　　　│　　　　┃",
            "　　┠───────────────────────────────────────────┼────┨",
            _RAW_L1_HYPHEN,
            _RAW_L2_HYPHEN,
            "　　┃　　　　　　　　　　│　　　　┃",
            "　　┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┷━━━━┛",
        ]

    def test_count(self):
        assert len(parse_entries(self._real_lines())) == 3

    def test_first_entry_souzoku(self):
        entries = parse_entries(self._real_lines())
        e = entries[0]
        assert e.receipt_number == "第10104号"
        assert e.receipt_date == "3月2日"
        assert e.category == "単独"
        assert e.purpose == "所有権移転・相続"
        assert e.property_type == "土地"
        assert e.location == "堺市堺区榎元町一丁10"
        assert e.remarks == ""

    def test_second_entry_with_gaichi(self):
        entries = parse_entries(self._real_lines())
        e = entries[1]
        assert e.receipt_number == "第10114号"
        assert e.location == "堺市北区金岡町1100-29"
        assert e.remarks == "外1"

    def test_third_entry_hyphen_number(self):
        entries = parse_entries(self._real_lines())
        e = entries[2]
        assert e.receipt_number == "第10080-号"

    def test_source_file_propagated(self):
        entries = parse_entries(self._real_lines(), source_file="sakai.pdf")
        assert all(e.source_file == "sakai.pdf" for e in entries)

    def test_raw_lines_preserved(self):
        lines = self._real_lines()
        entries = parse_entries(lines)
        assert entries[0].raw_line1 == _RAW_L1_SOUZOKU_TOCHI
        assert entries[0].raw_line2 == _RAW_L2_SOUZOKU_TOCHI

    def test_empty_input(self):
        assert parse_entries([]) == []

    def test_invalid_line2_skipped(self):
        """行2が解析できない場合はエントリ全体をスキップ。"""
        lines = [
            _RAW_L1_SOUZOKU_TOCHI,
            "　　┃　これは行2ではない　　　　　　│　　　　┃",
            _RAW_L1_SOUZOKU_GAICHI,
            _RAW_L2_SOUZOKU_GAICHI,
        ]
        entries = parse_entries(lines)
        assert len(entries) == 1
        assert entries[0].receipt_number == "第10114号"

    def test_returns_parsed_entry_instances(self):
        entries = parse_entries(self._real_lines())
        assert all(isinstance(e, ParsedEntry) for e in entries)
