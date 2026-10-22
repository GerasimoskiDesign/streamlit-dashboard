"""Excel export of the current dashboard view.

The export receives the frame that the page already got from ``allowed_rows`` and the
sidebar filters, so it can only ever contain permitted rows - there is no separate
"export query" that could forget a permission.
"""

from __future__ import annotations

from io import BytesIO

import pandas as pd

from salesreport.engine.common import COUNT_COLUMNS

EXPORT_COLUMNS = {
    "region": "Region",
    "block_name": "Shop / channel",
    "agent": "Agent",
    "agent_name": "Name",
    "detail": "Detail level",
    "renewals": "Total renewals",
    "store": "Store contracts",
    "selfservice": "Self-service",
    "digital": "Digital renewals",
    "digital_excl_cc": "Digital excl. C&C",
    "cc_only": "C&C only",
}


def view_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate the filtered rows to one line per shop/agent for export."""
    keys = ["region", "block_name", "agent", "agent_name", "detail"]
    counts = [c for c in COUNT_COLUMNS if c in frame]
    if not len(frame):
        return pd.DataFrame(columns=[*EXPORT_COLUMNS.values(), "Digital share"])
    table = (
        frame.assign(agent=frame["agent"].fillna(""), agent_name=frame["agent_name"].fillna(""))
        .groupby(keys, dropna=False)[counts]
        .sum()
        .reset_index()
    )
    table = table[[c for c in EXPORT_COLUMNS if c in table]].rename(columns=EXPORT_COLUMNS)
    table["Digital share"] = (table["Digital renewals"] / table["Total renewals"]).where(
        table["Total renewals"] > 0
    )
    return table.sort_values(
        ["Region", "Shop / channel", "Total renewals"], ascending=[True, True, False]
    )


def to_excel_bytes(frame: pd.DataFrame, title: str) -> bytes:
    """Workbook bytes for ``st.download_button``."""
    buffer = BytesIO()
    table = view_table(frame)
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        table.to_excel(writer, sheet_name="Current view", index=False, startrow=2)
        sheet = writer.sheets["Current view"]
        sheet["A1"] = title
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = 18
        share_col = table.columns.get_loc("Digital share") + 1
        for row in range(4, len(table) + 4):
            sheet.cell(row=row, column=share_col).number_format = "0.0%"
    return buffer.getvalue()
