import streamlit as st
import pandas as pd
import io
from Scheduler2 import build_schedule  # use the new Scheduler2 module

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="PEMRAP Volunteer Scheduler V2", layout="wide")
st.title("📅 PEMRAP Volunteer Scheduler V2")

# ── Session state init ───────────────────────────────────────────────────────
if "sched_df" not in st.session_state:
    st.session_state.sched_df       = None
    st.session_state.unassigned_df  = None
    st.session_state.breakdown_df   = None

# ── File upload & Run Scheduler ──────────────────────────────────────────────
uploaded = st.file_uploader("Upload survey info.xlsx", type="xlsx")
if uploaded and st.button("Run Scheduler"):
    df = pd.read_excel(uploaded)
    sched_df, unassigned_df, breakdown_df = build_schedule(df)
    # Parse day and shift for grid layout
    sched_df[['Day','Shift']] = (
        sched_df['Time Slot']
        .str.split(pat=' ', n=1, expand=True)
    )
    st.session_state.sched_df      = sched_df
    st.session_state.unassigned_df = unassigned_df
    st.session_state.breakdown_df  = breakdown_df

# ── Display once scheduled ──────────────────────────────────────────────────
if st.session_state.sched_df is not None:
    sched_df      = st.session_state.sched_df
    unassigned_df = st.session_state.unassigned_df
    breakdown_df  = st.session_state.breakdown_df

    days   = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
    shifts = ['10:00-14:00','14:00-18:00','18:00-22:00']

    # Build grid dict
    grid = {sh: {d: [] for d in days} for sh in shifts}
    for _, row in sched_df.iterrows():
        grid[row['Shift']][row['Day']].append((row['Name'], row['Role'], row['Fallback']))

    # ── HTML grid ──────────────────────────────────────────────────────────────
    html = "<table style='border-collapse: collapse; width:100%;'>"
    html += "<tr><th style='border:1px solid #ddd; padding:8px;'></th>" + \
            "".join(f"<th style='border:1px solid #ddd; padding:8px;'>{d}</th>" for d in days) + \
            "</tr>"
    for sh in shifts:
        for i in range(3):
            html += "<tr>"
            if i == 0:
                html += (
                    f"<td rowspan='3' style='border:1px solid #ddd; "
                    f"padding:8px; vertical-align:middle;'>{sh}</td>"
                )
            for d in days:
                cell = ""
                peoples = grid[sh][d]
                if i < len(peoples):
                    name, role, is_fb = peoples[i]
                    fmt_open = ""
                    fmt_close = ""
                    if role == 'mentor':
                        fmt_open = "<strong>"; fmt_close = "</strong>"
                    elif role == 'mentee':
                        fmt_open = "<span style='background:#add8e6; padding:2px 4px; border-radius:3px'>"
                        fmt_close = "</span>"
                    cell = f"{fmt_open}{name}{fmt_close}"
                    if is_fb:
                        cell += ' *'
                html += (
                    f"<td style='border:1px solid #ddd; padding:8px; vertical-align:top;'>{cell}</td>"
                )
            html += "</tr>"
    html += "</table>"

    st.markdown("### Schedule Preview", unsafe_allow_html=True)
    st.markdown(
        "Mentors are **bold**, mentees highlighted in light blue, and *asterisked* names are Forced Assignments.",
        unsafe_allow_html=True
    )
    st.markdown(html, unsafe_allow_html=True)

    # ── Raw tables ────────────────────────────────────────────────────────────
    st.subheader("Unassigned Volunteers")
    st.dataframe(unassigned_df, use_container_width=True)
    st.subheader("Preference Breakdown")
    st.dataframe(breakdown_df, use_container_width=True)

    # ── Fallback list ─────────────────────────────────────────────────────────
    st.subheader("Forced Assignments")
    fb = sched_df[sched_df["Fallback"]]
    if not fb.empty:
        for name in fb["Name"]:
            st.write(f"- {name}")
    else:
        st.write("_None_")

    # ── Excel export with Fallback tab ────────────────────────────────────────
    def to_excel_bytes():
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            wb = writer.book
            border_fmt    = wb.add_format({"border":1})
            mentor_fmt    = wb.add_format({"border":1,"bold":True})
            mentee_fmt    = wb.add_format({"border":1,"bg_color":"#ADD8E6"})
            volunteer_fmt = wb.add_format({"border":1})

            # Grid sheet
            ws = wb.add_worksheet("Grid")
            ws.write_blank(0, 0, None, border_fmt)
            for c, d in enumerate(days, start=1):
                ws.write(0, c, d, border_fmt)
            row = 1
            for sh in shifts:
                ws.merge_range(row, 0, row+2, 0, sh, border_fmt)
                for i in range(3):
                    for c, d in enumerate(days, start=1):
                        peoples = grid[sh][d]
                        if i < len(peoples):
                            name, role, is_fb = peoples[i]
                            fmt = (
                                mentor_fmt    if role == "mentor" else
                                mentee_fmt    if role == "mentee" else
                                volunteer_fmt
                            )
                            ws.write(row+i, c, name + (" *" if is_fb else ""), fmt)
                        else:
                            ws.write_blank(row+i, c, None, border_fmt)
                ws.set_row(row,   30)
                ws.set_row(row+1, 30)
                ws.set_row(row+2, 30)
                row += 3
            ws.set_column(0, 0, 16)
            ws.set_column(1, len(days), 22)

            # Schedule, Unassigned, Preferences sheets
            sched_df.drop(columns=['Day','Shift']) \
                .to_excel(writer, sheet_name="Schedule", index=False)
            unassigned_df.to_excel(writer, sheet_name="Unassigned", index=False)
            breakdown_df.to_excel(writer, sheet_name="Preferences", index=False)

            # Fallback sheet
            fallback_df = sched_df.loc[
                sched_df["Fallback"], ["Time Slot","Name","Role"]
            ]
            fallback_df.to_excel(writer, sheet_name="Fallback", index=False)

        return output.getvalue()

    excel_bytes = to_excel_bytes()
    st.download_button(
        "⬇️ Download schedule.xlsx",
        data=excel_bytes,
        file_name="schedule.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# Note: To reset and start over, just hit your browser’s Refresh (F5).

