import io
import re
import zipfile
from typing import List, Tuple, Dict

import pandas as pd
import streamlit as st

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


# ---- Oldal beállítások ----
st.set_page_config(
    page_title="Moovia PDF → Unilog Excel",
    page_icon="📦",
    layout="centered"
)

st.title("Moovia PDF → Unilog Excel")
st.caption("Order picking PDF-ek automatikus feldolgozása → Cikkszám + Mennyiség → letölthető Excel.")


# Ha nincs pdfplumber → hibát ír ki
if pdfplumber is None:
    st.error(
        "A pdfplumber csomag nincs telepítve a szerveren.\n\n"
        "A Streamlit Cloud automatikusan telepíti a requirements.txt alapján.\n"
        "Ha helyi gépen futtatod, telepítsd így:\n\n"
        "pip install pdfplumber"
    )
    st.stop()


# ---- Regexek ----
ORDER_ID_RE = re.compile(r"Order\s+picking:\s*([^\n|]+)", re.IGNORECASE)
ITEM_RE = re.compile(r"\b[vV](\d{5})\b")
PCS_INLINE_RE = re.compile(r"=\s*(\d+)\s*pcs", re.IGNORECASE)
PCS_ALONE_RE = re.compile(r"\b(\d+)\s*pcs\b", re.IGNORECASE)


def pdf_to_text(file_bytes: bytes) -> str:
    """PDF → összefűzött szöveg (összes oldal tartalma)."""
    parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def safe_name(raw: str) -> str:
    s = re.sub(r"[^0-9A-Za-z_\- ]+", "", raw).strip()
    return s.replace(" ", "_") or "ismeretlen"


def extract_order_id(text: str, fallback_name: str) -> str:
    """Order picking: utáni rész → fájlnév-rész"""
    m = ORDER_ID_RE.search(text)
    if m:
        return safe_name(m.group(1))

    base = fallback_name.rsplit("/", 1)[-1]
    base = base.rsplit(".", 1)[0]
    return safe_name(base)


def parse_items(text: str) -> List[Tuple[str, int]]:
    """Cikkszám + mennyiség kinyerése."""
    lines = text.splitlines()
    items: List[Tuple[str, int]] = []

    for i, line in enumerate(lines):
        matches = list(ITEM_RE.finditer(line))
        if not matches:
            continue

        inline = PCS_INLINE_RE.search(line)
        qty_inline = int(inline.group(1)) if inline else None

        for m in matches:
            code = "V" + m.group(1)
            qty = qty_inline

            if qty is None:
                for la_i in range(1, 4):
                    if i + la_i >= len(lines):
                        break
                    la = lines[i + la_i]
                    if ITEM_RE.search(la):
                        break
                    m2 = PCS_INLINE_RE.search(la) or PCS_ALONE_RE.search(la)
                    if m2:
                        qty = int(m2.group(1))
                        break

            if qty is not None:
                items.append((code, qty))

    return items


def items_to_dataframe(items: List[Tuple[str, int]]) -> pd.DataFrame:
    """Duplikált cikkszámok összevonása."""
    if not items:
        return pd.DataFrame(columns=["Cikkszám", "Mennyiség"])
    df = pd.DataFrame(items, columns=["Cikkszám", "Mennyiség"])
    df = df.groupby("Cikkszám", as_index=False)["Mennyiség"].sum()
    df = df.sort_values("Cikkszám").reset_index(drop=True)
    return df


# ---- Fájlfeltöltés UI ----

uploaded_files = st.file_uploader(
    "PDF-ek feltöltése (több is jelölhető egyszerre)",
    type=["pdf"],
    accept_multiple_files=True,
)

if not uploaded_files:
    st.info("Válaszd ki a Moovia 'Order picking' PDF-eket.")
else:
    outputs: Dict[str, bytes] = {}
    st.write(f"Feldolgozásra kijelölt fájlok száma: {len(uploaded_files)}")
    st.divider()

    for file in uploaded_files:
        raw = file.read()
        text = pdf_to_text(raw)

        order_id = extract_order_id(text, file.name)
        items = parse_items(text)
        df = items_to_dataframe(items)

        st.subheader(f"Fájl: {order_id}")
        st.dataframe(df, use_container_width=True)

        xbuf = io.BytesIO()
        with pd.ExcelWriter(xbuf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Kitarolas")
        xbuf.seek(0)

        xlsx_name = f"Order_picking_{order_id}.xlsx"
        outputs[xlsx_name] = xbuf.getvalue()

        st.download_button(
            label=f"Letöltés: {xlsx_name}",
            data=outputs[xlsx_name],
            file_name=xlsx_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    if outputs:
        st.divider()
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in outputs.items():
                zf.writestr(name, content)
        zip_buf.seek(0)

        st.download_button(
            label="Összes Excel ZIP-ben",
            data=zip_buf.getvalue(),
            file_name="Moovia_unilog_excels.zip",
            mime="application/zip",
        )


# ---- Oldalsáv ----
st.sidebar.header("Segítség")
st.sidebar.markdown(
    """
Használat:
1. Töltsd fel a Moovia 'Order picking' PDF-eket.
2. A rendszer kinyeri a cikkszámokat és a pcs mennyiséget.
3. Minden PDF-ből külön Excel készül.
4. Az összes letölthető egy ZIP-ben is.

Streamlit Cloud:
- kollégák bármilyen böngészőből használhatják
- semmit nem kell telepíteni
"""
)
