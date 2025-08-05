import streamlit as st
import pandas as pd
import io
from Scheduler2 import build_schedule, MAX_PER_SHIFT  # import max per shift constant

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="PEMRAP Volunteer Scheduler", layout="wide")
st.title("📅 PEMRAP Volunteer Scheduler")

# ── Session state init ───────────────────────────────────────────────────────
if "sched_df" not in st.session_state:
    st.session_state.sched_df = None
    st.session_state.unassigned_df = None
    st.session_state.breakdown_df = None

# ── File upload & Run Scheduler ──────────────────────────────────────────────
uploaded = st.file_uploader("Upload survey info.xlsx", type="xlsx")
if uploaded and st.button("Run Scheduler"):
    df = pd.read_excel(uploaded)
    sched_df, unassigned_df, breakdown_df = build_schedule(df)

    # Robustly parse Day and Shift from 'Time Slot'
    if 'Time Slot' in sched_df.columns:
        ts = sched_df['Time Slot'].astype(str)
        parts = ts.str.split(r"\s+", n=1, expand=True)
        sched_df['Day'] = parts[0].str.strip().str.title().fillna('')
        sched_df['Shift'] = (
            parts[1]
            .str.replace('[–—−]', '-', regex=True)
            .str.strip()
            .fillna('')
        )
    else:
        sched_df['Day'] = ''
        sched_df['Shift'] = ''

    # Save to session state
    st.session_state.sched_df = sched_df
    st.session_state.unassigned_df = unassigned_df
    st.session_state.breakdown_df = breakdown_df

# ── Display once scheduled ──────────────────────────────────────────────────
if st.session_state.sched_df is not None:
    sched_df = st.session_state.sched_df
    unassigned_df = st.session_state.unassigned_df
    breakdown_df = st.session_state.breakdown_df

    # Dynamically derive days and shifts present
    days = list(sched_df['Day'].unique())
    shifts = list(sched_df['Shift'].unique())

    # Build grid dict
    grid = {sh: {d: [] for d in days} for sh in shifts}
    for _, row in sched_df.iterrows():
        day = row['Day']
        sh = row['Shift']
        if not day or not sh or day not in grid.get(sh, {}):
            continue
        grid[sh][day].append((row['Name'], row.get('Role',''), row['Fallback']))

    # ── HTML grid ──────────────────────────────────────────────────────────────
    html = "<table style='border-collapse: collapse; width:100%;'>"
    html += "<tr><th style='border:1px solid #ddd; padding:8px;'></th>"
    for d in days:
        html += f"<th style='border:1px solid #ddd; padding:8px;'>{d}</th>"
    html += "</tr>"
    for sh in shifts:
        for i in range(MAX_PER_SHIFT):
            html += "<tr>"
            if i == 0:
                html += (
                    f"<td rowspan='{MAX_PER_SHIFT}' style='border:1px solid #ddd; padding:8px; vertical-align:middle;'>{sh}</td>"
                )
            for d in days:
                cell = ""
                peoples = grid.get(sh, {}).get(d, [])
                if i < len(peoples):
                    name, role, is_fb = peoples[i]
                    if role == 'mentor':
                        cell = f"<strong>{name}</strong>"
                    elif role == 'mentee':
                        cell = f"<span style='background:#add8e6; padding:2px 4px; border-radius:3px'>{name}</span>"
                    else:
                        cell = name
                    if is_fb:
                        cell += ' *'
                html += f"<td style='border:1px solid #ddd; padding:8px; vertical-align:top;'>{cell}</td>"
            html += "</tr>"
    html += "</table>"

    st.markdown("### Schedule Preview", unsafe_allow_html=True)
    st.markdown(
        "Mentors are **bold**, mentees highlighted in light blue, and *asterisked* names are forced assignments.",
        unsafe_allow_html=True
    )
    st.markdown(html, unsafe_allow_html=True)

    # ── Raw tables ────────────────────────────────────────────────────────────
    st.subheader("Unassigned Volunteers")
    st.dataframe(unassigned_df, use_container_width=True)
    st.subheader("Preference Breakdown")
    st.dataframe(breakdown_df, use_container_width=True)

    # ── Forced Assignments list ───────────────────────────────────────────────
    st.subheader("Forced Assignments")
    fb = sched_df[sched_df['Fallback']]
    if not fb.empty:
        for name in fb['Name']:
            st.write(f"- {name}")
    else:
        st.write("_None_")

    # ── Excel export ─────────────────────────────────────────────────────────
    def to_excel_bytes():
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            wb = writer.book
            border_fmt = wb.add_format({"border":1})
            mentor_fmt = wb.add_format({"border":1,"bold":True})
            mentee_fmt = wb.add_format({"border":1,"bg_color":"#ADD8E6"})
            volunteer_fmt = wb.add_format({"border":1})

            ws = wb.add_worksheet("Grid")
            ws.write_blank(0,0,None,border_fmt)
            for idx, d in enumerate(days, start=1):
                ws.write(0, idx, d, border_fmt)
            r = 1
            for sh in shifts:
                ws.merge_range(r,0,r+MAX_PER_SHIFT-1,0,sh,border_fmt)
                for i in range(MAX_PER_SHIFT):
                    for c, d in enumerate(days, start=1):
                        peoples = grid.get(sh, {}).get(d, [])
                        if i < len(peoples):
                            name, role, is_fb = peoples[i]
                            fmt = mentor_fmt if role=='mentor' else mentee_fmt if role=='mentee' else volunteer_fmt
                            ws.write(r+i, c, name + (" *" if is_fb else ""), fmt)
                        else:
                            ws.write_blank(r+i, c, None, border_fmt)
                for i in range(MAX_PER_SHIFT): ws.set_row(r+i, 30)
                r += MAX_PER_SHIFT
            ws.set_column(0,0,16)
            ws.set_column(1,len(days),22)

            sched_df.drop(columns=['Day','Shift']).to_excel(writer, sheet_name="Schedule", index=False)
            unassigned_df.to_excel(writer, sheet_name="Unassigned", index=False)
            breakdown_df.to_excel(writer, sheet_name="Preferences", index=False)
            fb_df = sched_df[sched_df['Fallback']][['Time Slot','Name','Role']]
            fb_df.to_excel(writer, sheet_name="Fallback", index=False)
        return output.getvalue()

    excel_bytes = to_excel_bytes()
    st.download_button(
        "⬇️ Download schedule.xlsx",
        data=excel_bytes,
        file_name="schedule.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# Note: Refresh (F5) to reset the app.
