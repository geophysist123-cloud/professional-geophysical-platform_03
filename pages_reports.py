from __future__ import annotations

import io
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak

from database.geophysical_store import save_report_metadata
from targeting.integration import combine_scores, contour_figure, NORMALIZERS, EVIDENCE_WEIGHT, CONCORDANCE_WEIGHT


def _data():
    df = st.session_state.get('integration_scored_df')
    if isinstance(df, pd.DataFrame) and not df.empty:
        return df.copy()
    return None


def _make_pdf(df, title, project, author, interpretation, normalization, mag_weight, grav_weight, include_maps):
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=landscape(A4), rightMargin=8*mm, leftMargin=8*mm, topMargin=8*mm, bottomMargin=8*mm)
    styles = getSampleStyleSheet()
    small = ParagraphStyle('small', parent=styles['BodyText'], fontSize=8, leading=10)
    story = [Paragraph(title, styles['Title'])]
    story.append(Paragraph(f'Project: {project} | Prepared by: {author} | Date: {datetime.now().strftime("%Y-%m-%d")}', small))
    story.append(Paragraph(f'Normalization: {normalization} | Magnetic: {mag_weight:.0f}% | Gravity: {grav_weight:.0f}% | Evidence: {EVIDENCE_WEIGHT:.0f}% | Concordance: {CONCORDANCE_WEIGHT:.0f}%', small))
    story += [Spacer(1, 5), Paragraph('Primary Interpretation', styles['Heading2']), Paragraph(interpretation or 'No interpretation supplied.', small), Spacer(1, 6)]
    summary = [
        ['Rows', str(len(df))],
        ['Both signals', str(int(df['Data_Confidence'].eq(100).sum()))],
        ['Magnetic only', str(int(df['Data_Confidence'].eq(60).sum()))],
        ['Gravity only', str(int(df['Data_Confidence'].eq(40).sum()))],
        ['No Score', str(int(df['Data_Confidence'].isna().sum()))],
    ]
    t = Table(summary, colWidths=[45*mm, 30*mm]); t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.35,colors.grey), ('BACKGROUND',(0,0),(0,-1),colors.lightgrey)]))
    story.append(t)
    if include_maps:
        specs=[('Mag_Normalized','Magnetic Normalized','viridis','0–100'),('Grav_Normalized','Gravity Normalized','plasma','0–100'),('Evidence_Score','Weighted Evidence','magma','0–100'),('Target_Score','Target Score','cividis','0–100')]
        interpretation = interpretation or ''
        for col, name, cmap, units in specs:
            if col not in df.columns or pd.to_numeric(df[col], errors='coerce').notna().sum() < 3:
                continue
            fig = contour_figure(df, col, f'{name} — {normalization}', cmap, units)
            ax=fig.axes[0]
            if interpretation:
                ax.text(0.02,0.98,interpretation,transform=ax.transAxes,va='top',ha='left',fontsize=8,bbox=dict(boxstyle='round',facecolor='white',alpha=0.82,edgecolor='black'))
            img=io.BytesIO(); fig.savefig(img,format='png',dpi=170,bbox_inches='tight'); img.seek(0); import matplotlib.pyplot as plt; plt.close(fig)
            story += [PageBreak(), Paragraph(name, styles['Heading2']), Image(img, width=250*mm, height=150*mm)]
    story += [PageBreak(), Paragraph('Target Ranking', styles['Heading2'])]
    cols=[c for c in ['Point_ID','Latitude','Longitude','Mag_Normalized','Grav_Normalized','Data_Confidence','Concordance','Target_Score','Target_Priority'] if c in df.columns]
    ranking=df[cols].sort_values('Target_Score',ascending=False,na_position='last').head(50)
    data=[cols] + [[str(row[c]) for c in cols] for _,row in ranking.iterrows()]
    rt=Table(data,repeatRows=1); rt.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.25,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.lightgrey),('FONTSIZE',(0,0),(-1,-1),7)])); story.append(rt)
    doc.build(story); out.seek(0); return out.getvalue()


def render_reports(user: dict):
    st.title('📄 Customizable Reports')
    df=_data()
    if df is None or df.empty:
        st.info('Run Integrated Targeting first so a scored dataset is available.')
        return
    c1,c2=st.columns(2)
    with c1:
        title=st.text_input('Report title','Professional Geophysical Exploration Report',key='report_title')
        project=st.text_input('Project / Area','Global Exploration Project',key='report_project')
        author=st.text_input('Prepared by',user.get('username','admin'),key='report_author')
    with c2:
        norm=st.selectbox('Normalization',list(NORMALIZERS.keys()),index=0,key='report_norm')
        mag_w=st.slider('Magnetic Weight %',0,100,60,key='report_mag_weight')
        interpretation=st.text_area('Primary interpretation to appear on report maps',value=st.session_state.get('map_interpretation',{}).get('text','High-score zones represent stronger integrated geophysical evidence and require geological review.'),height=140,key='report_interpretation')
    grav_w=100-mag_w
    scored=combine_scores(df,norm,mag_w,grav_w); scored['Evidence_Score']=scored['Mag_Contribution']+scored['Grav_Contribution']; st.session_state['integration_scored_df']=scored
    include_maps=st.checkbox('Include annotated contour maps',True,key='report_include_maps')
    if st.button('Generate Custom PDF',type='primary',use_container_width=True,key='report_generate'):
        pdf=_make_pdf(scored,title,project,author,interpretation,norm,mag_w,grav_w,include_maps)
        st.session_state['report_pdf']=pdf
        url = st.session_state.get('db_manager_url', '')
        schema = st.session_state.get('db_manager_schema', '') or None
        if url:
            project_key = project or 'DEMO_PROJECT'
            ok, msg = save_report_metadata(url, schema, project_key, title, 'PDF', author)
            if ok:
                st.caption('Report metadata saved to external database.')
            else:
                st.warning(msg)
        st.success('Custom PDF generated.')
    if st.session_state.get('report_pdf'):
        st.download_button('📥 Download PDF Report',st.session_state['report_pdf'],'geophysical_exploration_report.pdf','application/pdf',use_container_width=True,key='report_download')
    st.subheader('Report preview data')
    st.dataframe(scored.sort_values('Target_Score',ascending=False,na_position='last').head(30),use_container_width=True,hide_index=True)
