"""
app.py  ─ 不動産受付帳 抽出ツール (Streamlit UI)
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st
import streamlit_authenticator as stauth
import yaml

from core.exporter import load_excel_config, to_dataframe, to_excel_bytes
from core.filter import apply_filters, load_municipalities
from core.parser import parse_pdf

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="不動産受付帳 抽出ツール",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Config paths
# ---------------------------------------------------------------------------

_CONFIG_DIR      = Path(__file__).parent / "config"
_AUTH_YAML       = _CONFIG_DIR / "auth.yaml"
_CLIENTS_YAML    = _CONFIG_DIR / "clients.yaml"
_PREFECTURES_YAML = _CONFIG_DIR / "prefectures.yaml"
_CLIENT_ID       = "harada_tatemono"


@st.cache_data
def _load_client_config() -> dict:
    with open(_CLIENTS_YAML, encoding="utf-8") as f:
        return yaml.safe_load(f)[_CLIENT_ID]


@st.cache_data
def _load_municipalities() -> list[str]:
    return load_municipalities(_PREFECTURES_YAML)


def _load_auth_config() -> dict:
    """auth.yaml → なければ st.secrets (Community Cloud 用フォールバック) を返す。"""
    if _AUTH_YAML.exists():
        with open(_AUTH_YAML, encoding="utf-8") as f:
            return yaml.safe_load(f)
    try:
        # Streamlit Community Cloud では .streamlit/secrets.toml で設定
        def _deep(obj) -> dict:
            return {k: _deep(v) if hasattr(v, "items") else v for k, v in obj.items()}
        return {
            "credentials": _deep(st.secrets["credentials"]),
            "cookie":      _deep(st.secrets["cookie"]),
        }
    except Exception:
        st.error(
            "認証設定が見つかりません。"
            "`config/auth.yaml` を作成するか、"
            "Streamlit Secrets に `credentials` / `cookie` を設定してください。"
        )
        st.stop()


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

auth_cfg = _load_auth_config()

authenticator = stauth.Authenticate(
    auth_cfg["credentials"],
    auth_cfg["cookie"]["name"],
    auth_cfg["cookie"]["key"],
    auth_cfg["cookie"]["expiry_days"],
    auto_hash=False,   # auth.yaml には bcrypt ハッシュ済みパスワードを保存
)

name, auth_status, username = authenticator.login(
    location="main",
    fields={
        "Form name": "不動産受付帳 抽出ツール",
        "Username":  "ユーザー名",
        "Password":  "パスワード",
        "Login":     "ログイン",
    },
)

if auth_status is False:
    st.error("ユーザー名またはパスワードが正しくありません。")
    st.stop()
elif auth_status is None:
    st.stop()

# ── 以下、認証済みの場合のみ実行される ─────────────────────────────────────

# ---------------------------------------------------------------------------
# Config (認証後に読み込む)
# ---------------------------------------------------------------------------

client_cfg         = _load_client_config()
default_f          = client_cfg.get("default_filters", {})
excel_cfg          = load_excel_config(_CLIENTS_YAML, _CLIENT_ID)
municipalities_all = _load_municipalities()

# ---------------------------------------------------------------------------
# Sidebar: ユーザー情報 + 絞り込み条件
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown(f"ログイン中: **{name}**")
    authenticator.logout("ログアウト", location="sidebar")
    st.divider()

    st.header("絞り込み条件")

    # 市区町村
    st.subheader("市区町村")
    selected_municipalities: list[str] = st.multiselect(
        "市区町村を選択 (空=全件)",
        options=municipalities_all,
        default=[],
        placeholder="例: 堺市堺区、松原市 …",
    )

    st.divider()

    # 申請区分
    st.subheader("申請区分")
    _CAT_OPTIONS = ["単独", "連先", "連続", "嘱託"]
    _cat_defaults = set(default_f.get("categories", _CAT_OPTIONS))
    selected_categories: list[str] = [
        cat for cat in _CAT_OPTIONS
        if st.checkbox(cat, value=(cat in _cat_defaults), key=f"cat_{cat}")
    ]

    st.divider()

    # 登記目的
    st.subheader("登記目的")
    _PURPOSE_OPTIONS = ["相続", "売買", "抵当権設定", "その他"]
    _pur_defaults = set(default_f.get("purposes", _PURPOSE_OPTIONS))
    selected_purposes: list[str] = [
        p for p in _PURPOSE_OPTIONS
        if st.checkbox(p, value=(p in _pur_defaults), key=f"pur_{p}")
    ]

    st.divider()

    # 不動産種別
    st.subheader("不動産種別")
    _PROP_OPTIONS = ["土地", "建物", "区建", "共担"]
    _prop_defaults = set(default_f.get("property_types", _PROP_OPTIONS))
    selected_property_types: list[str] = [
        pt for pt in _PROP_OPTIONS
        if st.checkbox(pt, value=(pt in _prop_defaults), key=f"prop_{pt}")
    ]

# ---------------------------------------------------------------------------
# Main: タイトル + ファイルアップロード
# ---------------------------------------------------------------------------

st.title("不動産受付帳 抽出ツール")

uploaded_files = st.file_uploader(
    "受付帳 PDF をアップロード (最大10ファイル)",
    type=["pdf"],
    accept_multiple_files=True,
    help="法務局の不動産受付帳PDFを選択してください。",
)

if len(uploaded_files) > 10:
    st.warning("一度に処理できるのは最大10ファイルです。最初の10件のみ使用します。")
    uploaded_files = uploaded_files[:10]

# ---------------------------------------------------------------------------
# PDF 解析 (session_state でキャッシュ → フィルタ変更時に再解析しない)
# ---------------------------------------------------------------------------


def _file_key(files) -> tuple:
    return tuple(sorted((f.name, f.size) for f in files))


def _friendly_error(exc: Exception) -> str:
    """例外を日本語の短いメッセージに変換する。"""
    msg = str(exc).lower()
    if "password" in msg or "encrypted" in msg:
        return "パスワード保護されたPDFです。保護を解除してから再アップロードしてください。"
    if "invalid pdf" in msg or "not a pdf" in msg or "%pdf" in msg:
        return "PDFとして認識できないファイルです。"
    if "permission" in msg or "access" in msg:
        return "ファイルアクセスエラーです。再度アップロードしてください。"
    return f"解析に失敗しました ({type(exc).__name__}: {exc})"


if uploaded_files:
    new_key = _file_key(uploaded_files)
    if st.session_state.get("_file_key") != new_key:
        entries: list = []
        errors: list[str] = []
        warnings: list[str] = []
        bar = st.progress(0, text="PDF を解析中…")
        total = len(uploaded_files)
        for i, uf in enumerate(uploaded_files):
            try:
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(uf.getvalue())
                    tmp_path = Path(tmp.name)
                parsed = parse_pdf(tmp_path)
                for e in parsed:
                    e.source_file = uf.name
                entries.extend(parsed)
                tmp_path.unlink(missing_ok=True)
                if not parsed:
                    warnings.append(
                        f"{uf.name}: エントリが見つかりませんでした。"
                        "法務局の不動産受付帳PDFか確認してください。"
                    )
            except Exception as exc:
                errors.append(f"{uf.name}: {_friendly_error(exc)}")
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
            bar.progress((i + 1) / total, text=f"解析中: {uf.name}")
        bar.empty()

        st.session_state["_file_key"]      = new_key
        st.session_state["all_entries"]    = entries
        st.session_state["parse_errors"]   = errors
        st.session_state["parse_warnings"] = warnings

    all_entries: list   = st.session_state.get("all_entries", [])
    parse_errors: list  = st.session_state.get("parse_errors", [])
    parse_warnings: list = st.session_state.get("parse_warnings", [])

    for err in parse_errors:
        st.error(f"解析エラー: {err}")
    for warn in parse_warnings:
        st.warning(warn)

else:
    all_entries = []
    for k in ("_file_key", "all_entries", "parse_errors", "parse_warnings"):
        st.session_state.pop(k, None)

# ---------------------------------------------------------------------------
# フィルタ適用
# ---------------------------------------------------------------------------

filtered = apply_filters(
    all_entries,
    municipalities=selected_municipalities,
    categories=selected_categories,
    purpose_labels=selected_purposes,
    property_types=selected_property_types,
)

# ---------------------------------------------------------------------------
# 結果表示
# ---------------------------------------------------------------------------

if all_entries:
    st.markdown(
        f"**{len(filtered):,} 件** が条件に一致しました "
        f"(全 {len(all_entries):,} 件中)"
    )

    if filtered:
        df = to_dataframe(filtered, column_order=excel_cfg["column_order"])
        st.dataframe(df, use_container_width=True, hide_index=True)

        xlsx = to_excel_bytes(
            filtered,
            sheet_name=excel_cfg["sheet_name"],
            column_order=excel_cfg["column_order"],
        )
        st.download_button(
            label="Excel ダウンロード",
            data=xlsx,
            file_name="相続案件リスト.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        st.info("条件に一致するエントリがありません。絞り込み条件を確認してください。")

elif not uploaded_files:
    st.info("PDFファイルをアップロードしてください。")
